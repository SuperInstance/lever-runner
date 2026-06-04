"""
lever_core.py — Pure Python lever-runner core for Pyodide.
Zero dependencies beyond stdlib (hashlib, math, collections).
"""

import hashlib
import math
import time
from collections import OrderedDict

# ---------------------------------------------------------------------------
# BLAKE2b hashing
# ---------------------------------------------------------------------------

def _blake2b_hex(text: str) -> str:
    """Return BLAKE2b hex digest of text (256-bit)."""
    return hashlib.blake2b(text.encode("utf-8"), digest_size=32).hexdigest()


# ---------------------------------------------------------------------------
# Cosine similarity (pure Python)
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Simple whitespace + punctuation tokenizer with lowercasing."""
    chars = []
    for ch in text.lower():
        if ch.isalnum() or ch == " ":
            chars.append(ch)
        else:
            chars.append(" ")
    return "".join(chars).split()


class _Counter:
    """Tiny word-frequency dict."""
    __slots__ = ("data",)

    def __init__(self, words: list[str]):
        self.data: dict[str, int] = {}
        for w in words:
            self.data[w] = self.data.get(w, 0) + 1

    def keys(self):
        return self.data.keys()

    def __getitem__(self, k):
        return self.data.get(k, 0)


def _cosine_sim(a: str, b: str) -> float:
    """Cosine similarity between two short texts (bag-of-words)."""
    ca = _Counter(_tokenize(a))
    cb = _Counter(_tokenize(b))
    vocab = set(ca.keys()) | set(cb.keys())
    if not vocab:
        return 0.0
    dot = sum(ca[w] * cb[w] for w in vocab)
    mag_a = math.sqrt(sum(ca[w] ** 2 for w in vocab))
    mag_b = math.sqrt(sum(cb[w] ** 2 for w in vocab))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


# ---------------------------------------------------------------------------
# LRU Cache (OrderedDict-based)
# ---------------------------------------------------------------------------

class LRUCache:
    """Simple LRU cache backed by OrderedDict."""

    def __init__(self, maxsize: int = 256):
        self._maxsize = maxsize
        self._store: OrderedDict[str, str] = OrderedDict()

    def get(self, key: str):
        if key in self._store:
            self._store.move_to_end(key)
            return self._store[key]
        return None

    def put(self, key: str, value: str):
        if key in self._store:
            self._store.move_to_end(key)
            self._store[key] = value
        else:
            self._store[key] = value
            if len(self._store) > self._maxsize:
                self._store.popitem(last=False)

    def __len__(self):
        return len(self._store)

    def items(self):
        return list(self._store.items())


# ---------------------------------------------------------------------------
# Lever Core
# ---------------------------------------------------------------------------

class LeverCore:
    """Three-gate lever-runner: exact hash → cosine search → miss."""

    def __init__(self, threshold: float = 0.45):
        self._threshold = threshold
        # command_text -> command  (source of truth)
        self._commands: dict[str, str] = {}
        # hash -> command_text  (gate 1)
        self._hash_index: dict[str, str] = {}
        # LRU cache for recent queries
        self._cache = LRUCache(256)
        # token counter
        self._tokens_learned: int = 0

    # --- indexing helpers ---

    def _index(self, natural: str, command: str):
        self._commands[natural] = command
        self._hash_index[_blake2b_hex(natural)] = natural

    # --- public API ---

    def teach(self, natural: str, command: str) -> dict:
        """Teach a new natural-language → command mapping."""
        self._index(natural, command)
        self._tokens_learned += len(_tokenize(natural))
        self._cache.put(_blake2b_hex(natural), command)
        return {"status": "learned", "natural": natural, "command": command}

    def search(self, query: str) -> dict:
        """Run the three-gate pipeline on *query*."""
        t0 = time.time()
        q_hash = _blake2b_hex(query)

        # Gate 1 — exact hash match
        if q_hash in self._hash_index:
            cmd = self._commands[self._hash_index[q_hash]]
            latency = (time.time() - t0) * 1000
            self._cache.put(q_hash, cmd)
            return {
                "gate": 1,
                "match": "exact",
                "command": cmd,
                "query": query,
                "latency_ms": round(latency, 2),
            }

        # Gate 2 — cosine similarity search
        best_score = 0.0
        best_key = None
        for natural in self._commands:
            score = _cosine_sim(query, natural)
            if score > best_score:
                best_score = score
                best_key = natural

        if best_score >= self._threshold and best_key is not None:
            cmd = self._commands[best_key]
            latency = (time.time() - t0) * 1000
            self._cache.put(q_hash, cmd)
            return {
                "gate": 2,
                "match": "cosine",
                "command": cmd,
                "matched_input": best_key,
                "score": round(best_score, 4),
                "query": query,
                "latency_ms": round(latency, 2),
            }

        # Gate 3 — miss
        latency = (time.time() - t0) * 1000
        return {
            "gate": 3,
            "match": "miss",
            "command": None,
            "query": query,
            "latency_ms": round(latency, 2),
        }

    def export(self) -> dict:
        """Export all mappings."""
        return {"commands": dict(self._commands), "tokens_learned": self._tokens_learned}

    def stats(self) -> dict:
        return {
            "commands": len(self._commands),
            "tokens_learned": self._tokens_learned,
            "cache_size": len(self._cache),
        }


# ---------------------------------------------------------------------------
# Factory with pre-loaded commands
# ---------------------------------------------------------------------------

DEFAULT_COMMANDS = [
    ("list files", "ls -la"),
    ("list files long format", "ls -la"),
    ("show files", "ls"),
    ("show hidden files", "ls -la"),
    ("check disk usage", "df -h"),
    ("check disk", "df -h"),
    ("disk space", "df -h"),
    ("free memory", "free -h"),
    ("show memory", "free -h"),
    ("memory usage", "free -h"),
    ("current directory", "pwd"),
    ("where am i", "pwd"),
    ("print working directory", "pwd"),
    ("change directory", "cd"),
    ("go up", "cd .."),
    ("go home", "cd ~"),
    ("make directory", "mkdir"),
    ("create folder", "mkdir"),
    ("remove file", "rm"),
    ("remove directory", "rm -rf"),
    ("copy file", "cp"),
    ("move file", "mv"),
    ("rename file", "mv"),
    ("find file", "find . -name"),
    ("search text", "grep -r"),
    ("grep", "grep"),
    ("show processes", "ps aux"),
    ("running processes", "ps aux"),
    ("kill process", "kill"),
    ("network connections", "netstat -tlnp"),
    ("show ports", "ss -tlnp"),
    ("ip address", "ip addr"),
    ("ping host", "ping -c 4"),
    ("download file", "wget"),
    ("fetch url", "curl -O"),
    ("read file", "cat"),
    ("page file", "less"),
    ("tail log", "tail -f"),
    ("show end of file", "tail -n 50"),
    ("edit file", "vim"),
    ("nano editor", "nano"),
    ("change permissions", "chmod"),
    ("change owner", "chown"),
    ("disk usage summary", "du -sh *"),
    ("folder size", "du -sh"),
    ("system uptime", "uptime"),
    ("who is logged in", "who"),
    ("show date", "date"),
    ("calendar", "cal"),
    ("environment variables", "env"),
    ("set variable", "export"),
    ("alias command", "alias"),
    ("command history", "history"),
    ("compress tar", "tar -czf"),
    ("extract tar", "tar -xzf"),
    ("ssh connect", "ssh"),
    ("scp copy", "scp"),
    ("mount drive", "mount"),
    ("unmount drive", "umount"),
]


def create_lever() -> LeverCore:
    """Create a LeverCore pre-loaded with default commands."""
    core = LeverCore()
    for natural, command in DEFAULT_COMMANDS:
        core._index(natural, command)
        core._tokens_learned += len(_tokenize(natural))
    return core
