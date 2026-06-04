/**
 * worker.js — Web Worker that loads Pyodide and runs lever_core.py
 *
 * Messages in:
 *   { type: "init" }
 *   { type: "search", query: string }
 *   { type: "teach", natural: string, command: string }
 *   { type: "export" }
 *   { type: "stats" }
 *
 * Messages out:
 *   { type: "status", ... }
 *   { type: "search-result", ... }
 *   { type: "teach-result", ... }
 *   { type: "export-result", ... }
 *   { type: "stats-result", ... }
 */

let pyodide = null;

async function initPyodide() {
  try {
    self.postMessage({ type: "status", state: "loading-pyodide", msg: "Loading Pyodide runtime…" });

    pyodide = await loadPyodide({
      indexURL: "https://cdn.jsdelivr.net/pyodide/v0.25.1/full/"
    });

    self.postMessage({ type: "status", state: "loading-core", msg: "Loading lever_core.py…" });

    // Fetch and execute lever_core.py
    const resp = await fetch("lever_core.py");
    const code = await resp.text();
    await pyodide.runPythonAsync(code);

    // Create the lever instance
    await pyodide.runPythonAsync("lever = create_lever()");

    const stats = await getStats();

    self.postMessage({ type: "status", state: "ready", msg: "Ready", stats });
  } catch (err) {
    self.postMessage({ type: "status", state: "error", msg: "Init failed: " + err.message });
  }
}

async function search(query) {
  if (!pyodide) return;
  try {
    const escaped = query.replace(/\\/g, "\\\\").replace(/'/g, "\\'");
    const result = await pyodide.runPythonAsync(`lever.search('${escaped}')`);
    self.postMessage({ type: "search-result", result: result.toJs({ dict_converter: Object.fromEntries }) });
  } catch (err) {
    self.postMessage({ type: "search-result", result: { gate: 3, match: "error", command: null, query, latency_ms: 0, error: err.message } });
  }
}

async function teach(natural, command) {
  if (!pyodide) return;
  try {
    const en = natural.replace(/\\/g, "\\\\").replace(/'/g, "\\'");
    const ec = command.replace(/\\/g, "\\\\").replace(/'/g, "\\'");
    const result = await pyodide.runPythonAsync(`lever.teach('${en}', '${ec}')`);
    const stats = await getStats();
    self.postMessage({ type: "teach-result", result: result.toJs({ dict_converter: Object.fromEntries }), stats });
  } catch (err) {
    self.postMessage({ type: "teach-result", result: { status: "error", error: err.message } });
  }
}

async function doExport() {
  if (!pyodide) return;
  const result = await pyodide.runPythonAsync("lever.export()");
  self.postMessage({ type: "export-result", result: result.toJs({ dict_converter: Object.fromEntries }) });
}

async function getStats() {
  const s = await pyodide.runPythonAsync("lever.stats()");
  return s.toJs({ dict_converter: Object.fromEntries });
}

async function sendStats() {
  if (!pyodide) return;
  const stats = await getStats();
  self.postMessage({ type: "stats-result", stats });
}

// Message handler
self.onmessage = async (e) => {
  const { type } = e.data;
  switch (type) {
    case "init":
      await initPyodide();
      break;
    case "search":
      await search(e.data.query);
      break;
    case "teach":
      await teach(e.data.natural, e.data.command);
      break;
    case "export":
      await doExport();
      break;
    case "stats":
      await sendStats();
      break;
  }
};
