# Lever-Runner Skill Packs

Ready-to-use command packs for lever-runner. Each pack is a YAML file of `intent → command` mappings with optional `{{parameterized}}` templates.

## Quick Start

```bash
# Load a skill pack into your lever-runner database
python -m lever_runner seed --file skills/devops.md

# Or load all packs at once
for pack in skills/*.md; do
  python -m lever_runner seed --file "$pack"
done

# Now use them
python -m lever_runner "show docker logs for nginx"
python -m lever_runner "check disk usage"
python -m lever_runner "run tests with coverage"
```

## Available Packs

| Pack | Commands | Coverage |
|------|----------|----------|
| **devops.md** | 50 | Docker, Kubernetes, System, Network, Process Management |
| **git.md** | 40 | Basic, Branching, Investigation, Advanced |
| **python.md** | 30 | Package Management, Testing, Linting, Virtual Envs |
| **security.md** | 25 | File Permissions, SSH, SSL/TLS, Firewall |
| **data.md** | 20 | File Operations, JSON/CSV, Database |

**Total: 165 commands** covering the most common dev tasks.

## Format

Each command entry has:

```yaml
- intent: "human-readable description with {{param}}"
  command: "shell command with {{param}}"
  tags: [category, tags, for, search]
```

- **intent**: What the user would type in natural language
- **command**: The actual shell command to run
- **tags**: Categories for search/discovery
- **{{param}}**: Parameterized slots — lever-runner fills these from the user's input

## Parameterized Commands

Commands with `{{param}}` templates are the most powerful feature. When you say "show logs for nginx", lever-runner matches the intent template and fills `{{container}}` with "nginx":

```
"show logs for nginx"  →  docker logs --tail 100 nginx
"show logs for redis"  →  docker logs --tail 100 redis
"show logs for api"    →  docker logs --tail 100 api
```

One template teaches infinite variations.

## Creating Custom Packs

Create a `.md` file in `skills/` following the YAML format:

```yaml
# My Custom Pack — N Commands

```yaml
- intent: "my custom command with {{param}}"
  command: "my-command {{param}}"
  tags: [custom, tag]
```
```

Then seed it:

```bash
python -m lever_runner seed --file skills/my-pack.md
```

## Adding to Docker

```dockerfile
# In your Dockerfile
COPY skills/ /app/skills/
RUN for f in /app/skills/*.md; do python -m lever_runner seed --file "$f"; done
```

## Contributing

PRs welcome! Follow the existing format:
1. One YAML code block per file
2. Every command needs `intent`, `command`, and `tags`
3. Use `{{param}}` for variable parts
4. Keep commands safe (no `rm -rf /` equivalents)
5. Test with `python -m lever_runner "your intent here"`
