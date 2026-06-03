# Demo Recording Guide

## Prerequisites

```bash
# Install asciinema
pip install asciinema

# Optional: for GIF conversion
# Option A: agg (fast, recommended)
pip install agg
# Option B: asciicast → GIF via svg-term
npm install -g svg-term-cli
```

## Recording the Demo

```bash
cd /path/to/lever-runner

# Option 1: Run the scripted demo (simulated output, always looks perfect)
bash demo/demo-script.sh | asciinema rec demo.cast

# Option 2: Record live with real lever-runner (needs pip install -e . and LLM_BACKEND=passthrough)
asciinema rec demo.cast
# Then type/paste commands from the script manually
```

### Tips for a clean recording

- Set a minimal PS1: `export PS1='$ '`
- Use a dark terminal theme (Dracula, Solarized Dark, or Tokyo Night)
- Set font size to 14-16px for readability
- Terminal size: 80x24 is standard and works well for embedding
- Close other terminal tabs so no distractions appear

## Converting to GIF

### Using agg (recommended)

```bash
agg --theme dracula --font-size 14 demo.cast demo.gif
```

### Using svg-term

```bash
svg-term --in demo.cast --out demo.svg --theme dracula --window
# Then convert SVG → GIF with your preferred tool, or embed SVG directly
```

## Embedding in README

```markdown
## Demo

![lever-runner demo](demo/demo.gif)

> 90-second walkthrough: install, teach commands, parameterized templates, and the security model.
```

## Alternative: Upload to asciinema.org

```bash
asciinema upload demo.cast
# Paste the returned URL in your README:
# [![asciicast](https://asciinema.org/a/XXXXXXX.svg)](https://asciinema.org/a/XXXXXXX)
```
