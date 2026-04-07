#!/bin/bash
# SignalPilot Firecracker Setup — Linux
#
# The easiest platform. Just needs KVM module loaded.
#
# Usage:
#   chmod +x setup-linux.sh && ./setup-linux.sh

set -euo pipefail

echo ""
echo "========================================"
echo "  SignalPilot Firecracker Setup (Linux)  "
echo "========================================"
echo ""

# ─── Step 1: Check CPU virtualization ────────────────────────────────────────

VIRT_FLAGS=$(grep -c -E '(vmx|svm)' /proc/cpuinfo 2>/dev/null || echo "0")

if [ "$VIRT_FLAGS" -gt 0 ]; then
    echo "[OK] CPU virtualization supported (${VIRT_FLAGS} cores)"
else
    echo "[FAIL] CPU virtualization not available."
    echo "       Check BIOS/UEFI settings: enable Intel VT-x or AMD-V."
    exit 1
fi

# ─── Step 2: Check/load KVM module ──────────────────────────────────────────

if [ -e /dev/kvm ]; then
    echo "[OK] /dev/kvm available"
else
    echo "[...] Loading KVM module..."
    if grep -q "GenuineIntel" /proc/cpuinfo; then
        sudo modprobe kvm_intel 2>/dev/null || sudo modprobe kvm
    elif grep -q "AuthenticAMD" /proc/cpuinfo; then
        sudo modprobe kvm_amd 2>/dev/null || sudo modprobe kvm
    else
        sudo modprobe kvm
    fi

    if [ -e /dev/kvm ]; then
        echo "[OK] KVM module loaded"
    else
        echo "[FAIL] Could not load KVM module."
        echo "       Check: sudo dmesg | grep kvm"
        exit 1
    fi
fi

# ─── Step 3: Check KVM permissions ──────────────────────────────────────────

if [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
    echo "[OK] KVM permissions OK"
else
    echo "[...] Fixing KVM permissions..."
    sudo chmod 666 /dev/kvm 2>/dev/null || true
    sudo usermod -aG kvm "$(whoami)" 2>/dev/null || true
    echo "[OK] Added $(whoami) to kvm group (may need re-login)"
fi

# ─── Step 4: Check Docker ───────────────────────────────────────────────────

if command -v docker &>/dev/null; then
    DOCKER_VERSION=$(docker --version)
    echo "[OK] ${DOCKER_VERSION}"
else
    echo "[FAIL] Docker not found."
    echo "       Install: curl -fsSL https://get.docker.com | sh"
    exit 1
fi

# ─── Step 5: Verify Docker can see KVM ──────────────────────────────────────

echo "[...] Checking /dev/kvm inside Docker..."
KVM_CHECK=$(docker run --rm --device /dev/kvm alpine ls -la /dev/kvm 2>&1 || true)

if echo "$KVM_CHECK" | grep -q "/dev/kvm"; then
    echo "[OK] /dev/kvm available inside Docker — Firecracker ready!"
else
    echo "[WARN] Docker cannot access /dev/kvm."
    echo "       Check: ls -la /dev/kvm (should be crw-rw---- with group kvm)"
    echo "       Try: sudo chmod 666 /dev/kvm"
fi

# ─── Summary ─────────────────────────────────────────────────────────────────

echo ""
echo "========================================"
echo "  Setup Summary"
echo "========================================"
echo ""
echo "Ready! Run:"
echo "  docker run --device /dev/kvm signalpilot/sandbox"
echo ""
