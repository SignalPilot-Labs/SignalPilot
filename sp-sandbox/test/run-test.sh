#!/bin/bash
# SignalPilot Sandbox Test -- gVisor
# Verifies runsc is installed and working.
set -euo pipefail

echo ""
echo "SignalPilot Sandbox Test -- gVisor"
echo "==================================="
echo ""

echo "[OK] runsc: $(runsc --version 2>&1 | head -1)"

# Run a simple gVisor sandbox test
echo ""
echo "[...] Running gVisor sandbox test..."
runsc --rootless do -- python3 -c "print('gVisor sandbox working')"
echo "[OK] gVisor sandbox is working on your system!"
echo ""
