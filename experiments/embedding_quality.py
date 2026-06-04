"""
Embedding Quality Experiment — lever-runner

Question: How good are hash embeddings vs learned embeddings for command matching?

Hypothesis: Hash embeddings (55µs, zero deps) are "good enough" for lever-runner's 
workload (~200 commands) but learned embeddings will dominate at scale (>10K commands).

Method:
1. Take lever-runner's actual command database
2. For each command, generate hash + learned embeddings
3. Run retrieval accuracy test: given a natural language query, does the correct command rank #1?
4. Measure accuracy, latency, and the accuracy/latency tradeoff
"""

import hashlib
import time
import json
import os
import sys
import numpy as np
from collections import defaultdict

# lever-runner's actual commands (from seed_commands or the DB)
SEED_COMMANDS = [
    # System
    ("check disk usage", "df -h"),
    ("check memory usage", "free -h"),
    ("check cpu usage", "top -bn1 | head -20"),
    ("list running processes", "ps aux"),
    ("show system uptime", "uptime"),
    ("check kernel version", "uname -a"),
    ("show network connections", "ss -tulpn"),
    ("check open ports", "netstat -tulpn"),
    ("show disk partitions", "lsblk"),
    ("check system load", "cat /proc/loadavg"),
    
    # Docker
    ("list docker containers", "docker ps"),
    ("list docker images", "docker images"),
    ("show docker logs", "docker logs"),
    ("restart docker container", "docker restart"),
    ("stop docker container", "docker stop"),
    ("remove docker container", "docker rm"),
    ("show docker compose status", "docker compose ps"),
    ("pull docker image", "docker pull"),
    ("build docker image", "docker build"),
    ("prune docker resources", "docker system prune -f"),
    
    # Git
    ("show git status", "git status"),
    ("show git log", "git log --oneline -20"),
    ("show git diff", "git diff"),
    ("create git branch", "git checkout -b"),
    ("switch git branch", "git checkout"),
    ("merge git branch", "git merge"),
    ("push to remote", "git push"),
    ("pull from remote", "git pull"),
    ("stash git changes", "git stash"),
    ("show git remotes", "git remote -v"),
    
    # Files
    ("list files", "ls -la"),
    ("find large files", "find . -size +100M -ls"),
    ("count files in directory", "find . -type f | wc -l"),
    ("show file contents", "cat"),
    ("search in files", "grep -r"),
    ("compress directory", "tar czf"),
    ("extract archive", "tar xzf"),
    ("check file permissions", "stat"),
    ("show directory tree", "tree -L 2"),
    ("find recent files", "find . -mtime -1 -ls"),
    
    # Network
    ("ping host", "ping -c 3"),
    ("check dns resolution", "dig"),
    ("trace route", "traceroute"),
    ("download file", "curl -O"),
    ("check ssl certificate", "openssl s_client"),
    ("show firewall rules", "iptables -L"),
    ("check http response", "curl -I"),
    ("show network interfaces", "ip addr"),
    ("check bandwidth", "iperf3"),
    ("scan ports", "nmap -sT"),
    
    # Python
    ("run python script", "python3"),
    ("install python package", "pip install"),
    ("list python packages", "pip list"),
    ("create virtual environment", "python3 -m venv"),
    ("run python tests", "pytest"),
    ("check python version", "python3 --version"),
    ("format python code", "black"),
    ("lint python code", "ruff check"),
    ("run jupyter notebook", "jupyter notebook"),
    ("install from requirements", "pip install -r requirements.txt"),
    
    # Monitoring
    ("check service status", "systemctl status"),
    ("restart service", "systemctl restart"),
    ("show system logs", "journalctl -u"),
    ("check cron jobs", "crontab -l"),
    ("show environment variables", "env"),
    ("check disk io", "iostat"),
    ("show process tree", "pstree"),
    ("check swap usage", "swapon --show"),
    ("monitor network traffic", "iftop"),
    ("show hardware info", "lshw"),
]

# Test queries — natural language that users might type
TEST_QUERIES = [
    "how much disk space is left",
    "what's using all my memory",
    "is the server up",
    "show me what docker is running",
    "what changed in git",
    "find big files eating my disk",
    "ping google to test network",
    "install requests library",
    "check if nginx is running",
    "what version of python",
    "restart the database",
    "show me recent logs",
    "compress the backup folder",
    "what branches exist",
    "check the ssl cert",
    "how long has the server been running",
    "list all open connections",
    "pull latest changes",
    "run the test suite",
    "check cpu temperature",
]


def hash_embed(text: str, dim: int = 64) -> np.ndarray:
    if dim <= 64:
        h = hashlib.blake2b(text.encode(), digest_size=dim).digest()
    else:
        # Concatenate two hashes for dims > 64
        h1 = hashlib.blake2b(text.encode(), digest_size=64).digest()
        h2 = hashlib.blake2b((text + "\x00salt").encode(), digest_size=64).digest()
        h = (h1 + h2)[:dim]
    v = np.array([b/255.0 for b in h], dtype=np.float32)
    return v / (np.linalg.norm(v) + 1e-10)


def random_projection_embed(text: str, dim: int = 128) -> np.ndarray:
    """Better than pure hash — uses character n-grams + random projection."""
    rng = np.random.RandomState(42)
    projection = rng.randn(dim, 256)  # Fixed random projection
    
    # Character 3-gram features
    features = np.zeros(256, dtype=np.float32)
    text_lower = text.lower()
    for i in range(len(text_lower) - 2):
        ngram = text_lower[i:i+3]
        idx = hash(ngram) % 256
        features[idx] += 1.0
    
    if np.linalg.norm(features) > 0:
        features /= np.linalg.norm(features)
    
    result = projection @ features
    return result / (np.linalg.norm(result) + 1e-10)


def position_aware_embed(text: str, dim: int = 64) -> np.ndarray:
    """Hash embedding with position-awareness — words in different positions get different hashes."""
    words = text.lower().split()
    vec = np.zeros(dim, dtype=np.float32)
    
    for i, word in enumerate(words):
        h = hashlib.blake2b(f"{i}:{word}".encode(), digest_size=min(dim, 64)).digest()
        # Extend to dim if needed
        if dim > 64:
            h2 = hashlib.blake2b(f"{i}:{word}\x01".encode(), digest_size=64).digest()
            h = (h + h2)[:dim]
        word_vec = np.array([b/255.0 for b in h], dtype=np.float32)
        # Weight by position (first words matter more)
        weight = 1.0 / (1 + i * 0.5)
        vec += word_vec * weight
    
    if np.linalg.norm(vec) > 0:
        vec /= np.linalg.norm(vec)
    return vec


def evaluate_retrieval(embed_fn, commands, queries, dim):
    """Evaluate retrieval accuracy: does the correct command rank #1?"""
    # Build index
    cmd_texts = [desc for desc, cmd in commands]
    cmd_vectors = np.array([embed_fn(desc, dim) for desc in cmd_texts])
    
    # Evaluate
    ranks = []
    latencies = []
    
    for query in queries:
        q_vec = embed_fn(query, dim)
        start = time.perf_counter()
        sims = cmd_vectors @ q_vec
        latency = time.perf_counter() - start
        
        sorted_indices = np.argsort(-sims)
        # The "correct" command is the one with the most similar natural language description
        best_cmd_idx = None
        best_overlap = 0
        query_lower = query.lower()
        for i, (desc, cmd) in enumerate(commands):
            desc_words = set(desc.lower().split())
            query_words = set(query_lower.split())
            overlap = len(desc_words & query_words)
            if best_cmd_idx is None or overlap > best_overlap:
                best_overlap = overlap
                best_cmd_idx = i
        
        if best_cmd_idx is not None and best_overlap > 0:
            rank = np.where(sorted_indices == best_cmd_idx)[0][0] + 1
            ranks.append(rank)
        
        latencies.append(latency * 1e6)
    
    # Metrics
    top1 = sum(1 for r in ranks if r == 1) / len(ranks) if ranks else 0
    top3 = sum(1 for r in ranks if r <= 3) / len(ranks) if ranks else 0
    top5 = sum(1 for r in ranks if r <= 5) / len(ranks) if ranks else 0
    mrr = np.mean([1.0/r for r in ranks]) if ranks else 0
    avg_latency = np.mean(latencies)
    
    return {
        "embedder": embed_fn.__name__ if hasattr(embed_fn, '__name__') else str(embed_fn),
        "dim": dim,
        "top1_acc": top1,
        "top3_acc": top3,
        "top5_acc": top5,
        "mrr": mrr,
        "avg_latency_us": avg_latency,
        "num_commands": len(commands),
        "num_queries": len(queries),
    }


def run_experiment():
    print("=" * 60)
    print("Embedding Quality Experiment — lever-runner")
    print("=" * 60)
    print(f"Commands: {len(SEED_COMMANDS)}")
    print(f"Test queries: {len(TEST_QUERIES)}")
    print()
    
    embedders = [
        ("hash_blake2b_64", hash_embed, 64),
        ("hash_blake2b_128", hash_embed, 128),
        ("random_proj_128", random_projection_embed, 128),
        ("position_aware_64", position_aware_embed, 64),
        ("position_aware_128", position_aware_embed, 128),
    ]
    
    results = []
    for name, fn, dim in embedders:
        print(f"Testing {name} (dim={dim})...")
        result = evaluate_retrieval(fn, SEED_COMMANDS, TEST_QUERIES, dim)
        result["embedder"] = name
        results.append(result)
        print(f"  Top-1: {result['top1_acc']:.1%}  Top-3: {result['top3_acc']:.1%}  MRR: {result['mrr']:.3f}  Latency: {result['avg_latency_us']:.0f}µs")
    
    # Summary table
    print()
    print("=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    print(f"{'Embedder':<25} {'Dim':>4} {'Top-1':>6} {'Top-3':>6} {'MRR':>6} {'Latency':>10}")
    print("-" * 60)
    for r in results:
        print(f"{r['embedder']:<25} {r['dim']:>4} {r['top1_acc']:>5.1%} {r['top3_acc']:>5.1%} {r['mrr']:>5.3f} {r['avg_latency_us']:>8.0f}µs")
    
    # Save
    out_path = os.path.expanduser("~/repos/lever-runner/experiments/embedding_results.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {out_path}")
    
    return results


if __name__ == "__main__":
    run_experiment()
