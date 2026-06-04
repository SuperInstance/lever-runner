# lever-runner — Browser Edition

A **zero-server, zero-API-key** demo that runs lever-runner entirely in the browser using [Pyodide](https://pyodide.org/).

## How It Works

lever-runner has two tiers:

| Tier | Runtime | Latency | Accuracy |
|------|---------|---------|----------|
| **Fast-Loop (hash-based)** | Browser (Pyodide + NumPy) | ~1µs | 44% top-1 |
| **Slow-Loop (LLM)** | Server-side | ~200ms | 95%+ |

This browser demo runs the **Fast-Loop** tier entirely client-side. The position-aware embedder uses BLAKE2b hashing + NumPy vector math — no API calls needed.

## Run Locally

```bash
# Just open the file — no server required
open browser/index.html        # macOS
xdg-open browser/index.html    # Linux
start browser/index.html       # Windows
```

Or use a simple HTTP server:

```bash
cd browser/
python -m http.server 8080
# → http://localhost:8080
```

Works with `file://` protocol since everything is loaded from CDNs.

## Deploy

Push the `browser/` directory to any static host:

- **GitHub Pages** — drop in, enable Pages
- **Netlify** — drag & drop the folder
- **Vercel** — `vercel deploy browser/`
- **S3 + CloudFront** — upload as static site

No build step. No server. No API keys.

## Architecture

```
browser/
├── index.html    # Shell: loads Pyodide CDN, terminal UI
├── app.js        # Init Pyodide, inline Python core, handle I/O
├── styles.css    # Dark terminal theme (green-on-black)
└── README.md     # This file
```

The Python core (position-aware embedder + command database) is inlined in `app.js` and executed inside Pyodide. NumPy is loaded from the Pyodide package CDN.

## Security

The Fast-Loop blocks dangerous shell characters (`$`, `` ` ``, `;`, `&`, `|`, `>`, `<`, `!`) before matching. Since this runs entirely in-browser, there's no shell to inject anyway — but the check is preserved for parity with the server version.
