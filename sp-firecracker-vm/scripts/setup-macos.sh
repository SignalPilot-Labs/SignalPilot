#!/bin/bash
# SignalPilot Sandbox Setup — macOS
#
# Auto-detects the best sandbox backend:
#   - /dev/kvm available → Firecracker microVMs
#   - No /dev/kvm        → gVisor (user-space kernel, no KVM needed)
#
# Usage:
#   chmod +x setup-macos.sh && ./setup-macos.sh

set -euo pipefail

echo ""
echo "========================================"
echo "  SignalPilot Sandbox Setup (macOS)      "
echo "========================================"
echo ""

# ─── Step 1: Check macOS version ────────────────────────────────────────────

MACOS_VERSION=$(sw_vers -productVersion)
MACOS_MAJOR=$(echo "$MACOS_VERSION" | cut -d. -f1)
echo "[OK] macOS ${MACOS_VERSION}"

if [ "$MACOS_MAJOR" -lt 13 ]; then
    echo "[FAIL] macOS 13 (Ventura) or later required."
    exit 1
fi

# ─── Step 2: Check CPU architecture ─────────────────────────────────────────

ARCH=$(uname -m)
if [ "$ARCH" = "arm64" ]; then
    echo "[OK] Apple Silicon ($ARCH)"
elif [ "$ARCH" = "x86_64" ]; then
    echo "[OK] Intel Mac ($ARCH)"
else
    echo "[FAIL] Unknown architecture: $ARCH"
    exit 1
fi

# ─── Step 3: Check Docker Desktop ───────────────────────────────────────────

if command -v docker &>/dev/null; then
    DOCKER_VERSION=$(docker --version)
    echo "[OK] ${DOCKER_VERSION}"
else
    echo "[FAIL] Docker not found. Install Docker Desktop from docker.com"
    exit 1
fi

# ─── Step 4: Detect backend ─────────────────────────────────────────────────

echo "[...] Checking /dev/kvm inside Docker..."
KVM_CHECK=$(docker run --rm --device /dev/kvm alpine ls /dev/kvm 2>&1 || true)

BACKEND="gvisor"
if echo "$KVM_CHECK" | grep -q "/dev/kvm"; then
    BACKEND="firecracker"
    echo "[OK] /dev/kvm available — will use Firecracker"
else
    echo "[OK] No /dev/kvm — will use gVisor (user-space kernel sandbox)"
fi

# ─── Step 5: Verify gVisor binary availability ──────────────────────────────

if [ "$BACKEND" = "gvisor" ]; then
    echo "[...] Testing gVisor (runsc) on ${ARCH}..."
    GVISOR_CHECK=$(docker run --rm python:3.12-slim sh -c \
        "apt-get update -qq && apt-get install -qq -y curl >/dev/null 2>&1 && \
         curl -fsSL https://storage.googleapis.com/gvisor/releases/release/latest/${ARCH}/runsc -o /tmp/runsc && \
         chmod +x /tmp/runsc && /tmp/runsc --version 2>&1" 2>&1 || true)

    if echo "$GVISOR_CHECK" | grep -q "runsc version"; then
        echo "[OK] gVisor works on ${ARCH}"
    else
        echo "[FAIL] gVisor not available for ${ARCH}."
        echo "       Output: $GVISOR_CHECK"
        exit 1
    fi
fi

# ─── Summary ─────────────────────────────────────────────────────────────────

echo ""
echo "========================================"
echo "  Setup Summary"
echo "========================================"
echo ""

if [ "$BACKEND" = "firecracker" ]; then
    echo "Backend: Firecracker (microVM, ~200ms snapshot restore)"
    echo ""
    echo "Run:"
    echo "  docker compose --profile firecracker up -d"
else
    echo "Backend: gVisor (user-space kernel, ~50ms startup)"
    echo ""
    echo "Run:"
    echo "  docker compose up -d"
fi

echo ""
