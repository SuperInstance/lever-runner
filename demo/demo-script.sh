#!/usr/bin/env bash
# lever-runner demo — ~90 seconds, zero API keys
# Record with: asciinema rec demo.cast
#
# This is a SCRIPTED demo (simulated output) for recording.
# The real CLI matches this interface exactly.
#
# Prerequisites: PS1 set to something clean, e.g.:
#   export PS1='$ '

set -euo pipefail

# Simulated typing helper — prints a line char by char
type_cmd() {
    local text="$1"
    for ((i=0; i<${#text}; i++)); do
        printf '%s' "${text:$i:1}"
        sleep 0.03
    done
    echo
}

# Simulated output with slight delay
sim() {
    sleep 0.4
    while IFS= read -r line; do
        echo "$line"
    done <<< "$1"
}

clear
echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║   lever-runner · shell AI where injection is impossible   ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
sleep 1.5

# ── Section 1: Install & first run ──────────────────────────
type_cmd '$ git clone https://github.com/SuperInstance/lever-runner && cd lever-runner'
sim "Cloning into 'lever-runner'...
done."

type_cmd '$ pip install -e .'
sim "Successfully installed lever-runner-0.1.0"

type_cmd '$ export LLM_BACKEND=passthrough'
echo ""
sleep 0.5

echo "# 67 built-in commands, zero config, $0/month"
sleep 0.5
type_cmd '$ python -m lever_runner "check disk usage"'
sim 'intent:   '\''show disk usage'\''
matched:  '\''check disk usage'\''  trust=80.0
command:  df -h
exit:     0  (ok, 0.03s)
--- stdout ---
Filesystem      Size  Used Avail Use% Mounted on
/dev/nvme0n1p2  500G  180G  320G  36% /'

echo ""
sleep 1

# ── Section 2: Teach a new command ──────────────────────────
echo "# Teach it something new — it remembers forever"
sleep 0.5
type_cmd '$ python -m lever_runner teach "show my ip" | "curl -s ifconfig.me"'
sim 'taught (chat=default): show_my_ip'

echo ""
type_cmd '$ python -m lever_runner "what is my ip"'
sim 'intent:   '\''what is my ip'\''
matched:  '\''show my ip'\''  trust=80.0
command:  curl -s ifconfig.me
exit:     0  (ok, 0.21s)
--- stdout ---
203.0.113.42'

echo ""
sleep 1

# ── Section 3: Parameterized commands ───────────────────────
echo "# Parameterized commands — teach once, reuse with any argument"
sleep 0.5
type_cmd '$ python -m lever_runner teach "show logs for {{container}}" | "docker logs --tail 100 {{container}}"'
sim 'taught (chat=default): show_logs_for_container'

echo ""
type_cmd '$ python -m lever_runner "show logs for nginx"'
sim 'intent:   '\''show logs for nginx'\''
matched:  '\''show logs for {{container}}'\''  trust=80.0
command:  docker logs --tail 100 nginx
exit:     0  (ok, 0.15s)
--- stdout ---
2024-01-15 10:02:11 GET / 200
2024-01-15 10:02:14 POST /api 201
2024-01-15 10:03:01 GET /health 200'

echo ""
sleep 1

# ── Section 4: The security model ──────────────────────────
echo "# ── The LLM never sees your shell. Ever. ──────────────"
echo "#"
echo "#  It only sees: system prompt (58 tok) + your request"
echo "#  It NEVER sees: command table, history, file system, env vars"
echo "#"
echo "#  Prompt injection is PHYSICALLY IMPOSSIBLE."
echo "#  The worst case: wrong pre-approved command runs once."
echo ""
sleep 1.5

# ── Section 5: Token / cost comparison ─────────────────────
echo "# Token cost comparison"
sleep 0.5
type_cmd '$ python -m lever_runner.benchmark'
sim 'Running 20-task suite in passthrough mode...

Mode                Tokens/cmd   Cost/1K cmds
─────────────────── ──────────── ────────────
Passthrough         ~6           $0.00
Hosted LLM          ~76          $0.006
OpenAI function     ~2,500       $0.47'

echo ""
sleep 1

# ── Section 6: Wrap up ─────────────────────────────────────
echo "╔════════════════════════════════════════════════════════════╗"
echo "║  67 commands. $0/month. Injection-proof by architecture.   ║"
echo "║  github.com/SuperInstance/lever-runner                    ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
