"""
Train a tiny neural command embedder on RTX 4050.

Architecture: 2-layer MLP (vocab → 128 → 64)
Training data: lever-runner's 80 seed commands + natural language paraphrases
Loss: contrastive — similar descriptions should produce similar vectors

Target: >60% top-1 accuracy while staying <100µs latency
"""

import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
import hashlib
import time
import json
import os

# Training pairs: (natural_language, command_description)
TRAINING_PAIRS = [
    ("how much disk space is left", "check disk usage"),
    ("show me disk usage", "check disk usage"),
    ("df command", "check disk usage"),
    ("what's using my memory", "check memory usage"),
    ("show ram usage", "check memory usage"),
    ("free memory check", "check memory usage"),
    ("is the cpu busy", "check cpu usage"),
    ("show processor load", "check cpu usage"),
    ("what's running on the system", "check cpu usage"),
    ("list all processes", "list running processes"),
    ("show me what's running", "list running processes"),
    ("ps command", "list running processes"),
    ("how long has server been up", "show system uptime"),
    ("uptime", "show system uptime"),
    ("check server uptime", "show system uptime"),
    ("what containers are running", "list docker containers"),
    ("show docker", "list docker containers"),
    ("docker ps", "list docker containers"),
    ("show me the git log", "show git log"),
    ("recent commits", "show git log"),
    ("git history", "show git log"),
    ("what changed", "show git diff"),
    ("diff", "show git diff"),
    ("git differences", "show git diff"),
    ("create a new branch", "create git branch"),
    ("new branch", "create git branch"),
    ("make branch", "create git branch"),
    ("push to origin", "push to remote"),
    ("upload commits", "push to remote"),
    ("git push", "push to remote"),
    ("install a python package", "install python package"),
    ("pip install something", "install python package"),
    ("add a library", "install python package"),
    ("check if nginx is running", "check service status"),
    ("service status", "check service status"),
    ("is it running", "check service status"),
    ("restart the database", "restart service"),
    ("restart postgres", "restart service"),
    ("restart service", "restart service"),
    ("show me recent logs", "show system logs"),
    ("tail the logs", "show system logs"),
    ("check logs", "show system logs"),
    ("compress the backup", "compress directory"),
    ("tar this folder", "compress directory"),
    ("make an archive", "compress directory"),
    ("find big files", "find large files"),
    ("what's eating my disk", "find large files"),
    ("large files", "find large files"),
    ("ping test", "ping host"),
    ("check if host is up", "ping host"),
    ("ping google", "ping host"),
    ("check the certificate", "check ssl certificate"),
    ("ssl check", "check ssl certificate"),
    ("verify tls", "check ssl certificate"),
]


class CharacterTokenizer:
    """Character-level tokenizer — zero vocab, handles any input."""
    def __init__(self, max_len=64):
        self.max_len = max_len
    
    def encode(self, text):
        # Normalize
        text = text.lower().strip()[:self.max_len]
        # Character to int (ASCII)
        tokens = [min(ord(c), 127) / 127.0 for c in text]
        # Pad to max_len
        while len(tokens) < self.max_len:
            tokens.append(0.0)
        return torch.tensor(tokens, dtype=torch.float32)


class CommandEmbedder(nn.Module):
    """Tiny 2-layer MLP embedder."""
    def __init__(self, input_dim=64, hidden_dim=128, output_dim=64):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.LayerNorm(hidden_dim),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.LayerNorm(hidden_dim),
            nn.Linear(hidden_dim, output_dim),
        )
    
    def forward(self, x):
        emb = self.net(x)
        return emb / (emb.norm(dim=1, keepdim=True) + 1e-8)


class ContrastiveLoss(nn.Module):
    """InfoNCE-style contrastive loss."""
    def __init__(self, temperature=0.1):
        super().__init__()
        self.temperature = temperature
    
    def forward(self, anchor, positive, negatives):
        # anchor: [B, D], positive: [B, D], negatives: [N, D]
        pos_sim = torch.sum(anchor * positive, dim=1) / self.temperature  # [B]
        neg_sim = torch.matmul(anchor, negatives.T) / self.temperature     # [B, N]
        
        logits = torch.cat([pos_sim.unsqueeze(1), neg_sim], dim=1)  # [B, 1+N]
        labels = torch.zeros(logits.shape[0], dtype=torch.long, device=logits.device)
        
        return nn.functional.cross_entropy(logits, labels)


def train():
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    print(f"Training on: {device}")
    if device == 'cuda':
        print(f"GPU: {torch.cuda.get_device_name(0)}")
    
    tokenizer = CharacterTokenizer(max_len=64)
    model = CommandEmbedder().to(device)
    criterion = ContrastiveLoss()
    optimizer = optim.Adam(model.parameters(), lr=1e-3)
    
    # Prepare training data
    # Group by target command
    from collections import defaultdict
    command_groups = defaultdict(list)
    for nl, cmd in TRAINING_PAIRS:
        command_groups[cmd].append(nl)
    
    unique_commands = list(command_groups.keys())
    
    # Training loop
    print(f"\nTraining: {len(TRAINING_PAIRS)} pairs, {len(unique_commands)} unique commands")
    print(f"Model params: {sum(p.numel() for p in model.parameters()):,}")
    
    for epoch in range(200):
        total_loss = 0
        random_order = np.random.permutation(len(TRAINING_PAIRS))
        
        batch_size = 32
        for i in range(0, len(TRAINING_PAIRS), batch_size):
            batch_indices = random_order[i:i+batch_size]
            batch = [TRAINING_PAIRS[j] for j in batch_indices]
            
            # Anchor = natural language
            anchors = torch.stack([tokenizer.encode(nl) for nl, _ in batch]).to(device)
            
            # Positive = command description
            positives = torch.stack([tokenizer.encode(cmd) for _, cmd in batch]).to(device)
            
            # Negatives = other commands
            neg_cmds = [random.choice([c for c in unique_commands if c != cmd]) for _, cmd in batch]
            negatives = torch.stack([tokenizer.encode(c) for c in neg_cmds]).to(device)
            
            anchor_emb = model(anchors)
            pos_emb = model(positives)
            neg_emb = model(negatives)
            
            loss = criterion(anchor_emb, pos_emb, neg_emb)
            
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            
            total_loss += loss.item()
        
        if epoch % 50 == 0:
            print(f"  Epoch {epoch}: loss={total_loss:.4f}")
    
    print(f"\nFinal loss: {total_loss:.4f}")
    
    # Evaluate
    print("\n=== EVALUATION ===")
    
    # Build index of all command descriptions
    cmd_tensors = torch.stack([tokenizer.encode(cmd) for cmd in unique_commands]).to(device)
    with torch.no_grad():
        cmd_embeddings = model(cmd_tensors)
    
    test_queries = [
        "how much disk space left",
        "show me running containers",
        "what changed in git",
        "restart the server",
        "install requests library",
        "check if it's up",
        "find big files",
        "show logs",
        "make a new branch",
        "compress this",
    ]
    
    correct = 0
    total = 0
    for query in test_queries:
        q_tensor = tokenizer.encode(query).unsqueeze(0).to(device)
        with torch.no_grad():
            q_emb = model(q_tensor)
        
        sims = torch.matmul(q_emb, cmd_embeddings.T).squeeze(0)
        top_idx = torch.argmax(sims).item()
        predicted = unique_commands[top_idx]
        
        # Find ground truth (match to closest training pair)
        best_match = None
        best_overlap = 0
        q_words = set(query.lower().split())
        for nl, cmd in TRAINING_PAIRS:
            overlap = len(q_words & set(nl.lower().split()))
            if overlap > best_overlap:
                best_overlap = overlap
                best_match = cmd
        
        is_correct = predicted == best_match if best_match else False
        correct += int(is_correct)
        total += 1
        
        symbol = "✅" if is_correct else "❌"
        print(f"  {symbol} '{query}' → {predicted} (expected: {best_match})")
    
    accuracy = correct / total if total > 0 else 0
    print(f"\nTop-1 accuracy: {accuracy:.1%}")
    
    # Latency benchmark
    q_tensor = tokenizer.encode("check disk usage").unsqueeze(0).to(device)
    if device == 'cuda':
        torch.cuda.synchronize()
    start = time.perf_counter()
    for _ in range(10000):
        with torch.no_grad():
            _ = model(q_tensor)
    if device == 'cuda':
        torch.cuda.synchronize()
    latency = (time.perf_counter() - start) / 10000 * 1e6
    print(f"Inference latency: {latency:.0f}µs")
    
    # Save model
    model_path = os.path.expanduser("~/repos/lever-runner/experiments/neural_embedder.pt")
    torch.save({
        'model_state': model.state_dict(),
        'accuracy': accuracy,
        'latency_us': latency,
        'params': sum(p.numel() for p in model.parameters()),
    }, model_path)
    print(f"Model saved to {model_path}")
    
    # Compare
    print("\n=== COMPARISON ===")
    print(f"  Hash blake2b:       0% top-1")
    print(f"  Position-aware:    44% top-1, 1µs")
    print(f"  Neural (trained):  {accuracy:.0%} top-1, {latency:.0f}µs")
    
    if accuracy > 0.6:
        print("\n✅ NEURAL WINS: >60% accuracy achieved!")
    elif accuracy > 0.44:
        print("\n⚠️ NEURAL BEATS POSITION-AWARE but below 60% target")
    else:
        print("\n❌ Neural underperforms — need more training data or architecture changes")


if __name__ == "__main__":
    import random
    random.seed(42)
    np.random.seed(42)
    torch.manual_seed(42)
    train()
