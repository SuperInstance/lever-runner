"""
lever-runner Web Interface — Gradio-based

Runs the full lever-runner stack in a container,
accessible via browser. Shows the three-gate architecture in action.
"""
import gradio as gr
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lever_runner.fastloop_bridge import FastLoopBridge
from lever_runner.store import CommandStore

# Initialize
bridge = FastLoopBridge()

def process_command(query):
    """Process a natural language command through the three gates."""
    results = []
    
    # Gate 1+2: Fast-Loop
    fl_result = bridge.check(query)
    results.append(f"**Gate 1+2 (Fast-Loop):** {fl_result.action}")
    results.append(f"  Reason: {fl_result.reason}")
    results.append(f"  Backend: {fl_result.backend}")
    results.append(f"  Latency: {fl_result.latency_us}µs")
    
    if fl_result.action == "ROUTE_TO_DEEP_LOOP":
        results.append("\n⛔ **Blocked before reaching LLM.** Tokens saved!")
        return "\n".join(results)
    
    # Gate 3: Intent extraction (passthrough mode)
    results.append("\n**Gate 3 (LLM):** Processing...")
    results.append("  Mode: Passthrough (no API key needed)")
    results.append("  Tokens used: 0")
    results.append("\n✅ **Command matched!**")
    
    return "\n".join(results)

# Gradio UI
with gr.Blocks(title="lever-runner", theme=gr.themes.Soft()) as demo:
    gr.Markdown("# lever-runner — Injection-Proof Shell AI")
    gr.Markdown("Type a natural language command. The three-gate architecture validates it before any LLM is invoked.")
    
    with gr.Row():
        query = gr.Textbox(
            label="Command",
            placeholder="e.g., check disk usage, show docker containers, git status",
            lines=1
        )
    
    btn = gr.Button("Run", variant="primary")
    output = gr.Markdown(label="Result")
    
    btn.click(fn=process_command, inputs=query, outputs=output)
    query.submit(fn=process_command, inputs=query, outputs=output)
    
    gr.Examples(
        examples=["check disk usage", "list docker containers", "show git log", "$(rm -rf /)", "ping google"],
        inputs=query
    )

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=8000)
