#!/bin/bash
# SignalPilot Sandbox Setup -- Linux
#
# gVisor (runsc) does not require KVM. Just needs Docker.
#
# Usage:
#   chmod +x setup-linux.sh && ./setup-linux.sh

set -euo pipefail

echo ""
echo "========================================"
echo "  SignalPilot Sandbox Setup (Linux)     "
echo "========================================"
echo ""

# ─── Step 1: Check Docker ───────────────────────────────────────────────────

if command -v docker &>/dev/null; then
    DOCKER_VERSION=$(docker --version)
    echo "[OK] ${DOCKER_VERSION}"
else
    echo "[FAIL] Docker not found."
    echo "       Install: curl -fsSL https://get.docker.com | sh"
    exit 1
fi

# ─── Step 2: Verify Docker can run containers ────────────────────────────────

echo "[...] Verifying Docker is working..."
if docker run --rm hello-world &>/dev/null; then
    echo "[OK] Docker is working"
else
    echo "[FAIL] Docker run failed. Check Docker daemon status."
    exit 1
fi

# ─── Summary ─────────────────────────────────────────────────────────────────

echo ""
echo "========================================"
echo "  Setup Summary"
echo "========================================"
echo ""
echo "Ready! Run:"
echo "  docker run --cap-add SYS_PTRACE --cap-add SYS_ADMIN signalpilot/sandbox"
echo ""
