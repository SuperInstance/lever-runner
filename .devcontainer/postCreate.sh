#!/bin/bash
pip install -e .
# Run the demo to verify everything works
python3 demo/demo.py
echo ""
echo "✅ lever-runner is ready!"
echo "Run: python3 -m lever_runner"
