// lever-runner — Browser Edition
// Pyodide-powered, zero-server, zero-API-key command finder

let pyodide;
const output = document.getElementById('output');
const input = document.getElementById('input');
const loadMsg = document.getElementById('load-msg');

function print(text, cls = '') {
    const p = document.createElement('p');
    p.className = cls;
    p.textContent = text;
    output.appendChild(p);
    output.scrollTop = output.scrollHeight;
}

function printHTML(html) {
    const p = document.createElement('p');
    p.innerHTML = html;
    output.appendChild(p);
    output.scrollTop = output.scrollHeight;
}

const PYTHON_CORE = `
import hashlib
import numpy as np
import json

def position_aware_embed(text, dim=64):
    words = text.lower().split()
    vec = np.zeros(dim, dtype=np.float32)
    for i, word in enumerate(words):
        h = hashlib.blake2b(f"{i}:{word}".encode(), digest_size=dim).digest()
        word_vec = np.array([b / 255.0 for b in h], dtype=np.float32)
        weight = 1.0 / (1 + i * 0.5)
        vec += word_vec * weight
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec

def cosine_sim(a, b):
    return float(np.dot(a, b))

COMMANDS = {
    "check disk usage": "df -h",
    "check memory usage": "free -h",
    "check cpu usage": "top -bn1 | head -20",
    "list running processes": "ps aux",
    "show system uptime": "uptime",
    "list docker containers": "docker ps",
    "list docker images": "docker images",
    "show docker logs": "docker logs",
    "show git status": "git status",
    "show git log": "git log --oneline -20",
    "show git diff": "git diff",
    "create git branch": "git checkout -b",
    "push to remote": "git push",
    "pull from remote": "git pull",
    "list files": "ls -la",
    "find large files": "find . -size +100M -ls",
    "search in files": "grep -r",
    "ping host": "ping -c 3",
    "install python package": "pip install",
    "run python tests": "pytest",
    "check service status": "systemctl status",
    "restart service": "systemctl restart",
    "show system logs": "journalctl -u",
    "compress directory": "tar czf",
    "extract archive": "tar xzf",
    "check network connections": "ss -tulpn",
    "show firewall rules": "iptables -L",
    "check ssl certificate": "openssl s_client",
    "download file": "curl -O",
    "show hardware info": "lshw",
}

cmd_embeddings = {}
for desc, cmd in COMMANDS.items():
    cmd_embeddings[desc] = position_aware_embed(desc)

def find_command(query, top_k=3):
    q_vec = position_aware_embed(query)
    scores = [(desc, cosine_sim(q_vec, emb)) for desc, emb in cmd_embeddings.items()]
    scores.sort(key=lambda x: -x[1])
    results = []
    for desc, score in scores[:top_k]:
        results.append({"description": desc, "command": COMMANDS[desc], "confidence": round(score, 4)})
    return json.dumps(results)

def process_query(query):
    dangerous = ['$', '\`', ';', '&', '|', '>', '<', '!']
    for char in dangerous:
        if char in query:
            return json.dumps({"error": f"Blocked: dangerous character '{char}'"})

    results = find_command(query)
    return results
`;

async function init() {
    try {
        pyodide = await loadPyodide();
        print('Python runtime loaded. Installing numpy...', 'system');

        await pyodide.loadPackage('numpy');

        print('Numpy ready. Loading lever-runner core...', 'system');

        await pyodide.runPythonAsync(PYTHON_CORE);

        loadMsg.remove();
        print('✓ lever-runner ready! Type a natural language command:', 'success');
        input.disabled = false;
        input.focus();
    } catch (e) {
        loadMsg.remove();
        print(`Failed to initialize: ${e.message}`, 'error');
    }
}

async function handleInput(query) {
    print(`❯ ${query}`, 'input');

    try {
        // Escape single quotes for Python string
        const escaped = query.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
        const result = pyodide.runPython(`process_query('${escaped}')`);
        const parsed = JSON.parse(result);

        if (parsed.error) {
            print(`⛔ ${parsed.error}`, 'error');
        } else if (Array.isArray(parsed)) {
            parsed.forEach((r, i) => {
                const pct = (r.confidence * 100).toFixed(1);
                if (i === 0) {
                    print(`✅ [${pct}%] ${r.description}  →  ${r.command}`, 'best');
                } else {
                    print(`   [${pct}%] ${r.description}  →  ${r.command}`, 'alt');
                }
            });
        }
    } catch (e) {
        print(`Error: ${e.message}`, 'error');
    }
}

input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && input.value.trim()) {
        handleInput(input.value.trim());
        input.value = '';
    }
});

init();
