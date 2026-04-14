#!/bin/bash
# Entry point for the Firecracker test container.
# Creates the ext4 rootfs at runtime (needs privileges for mount),
# then boots a microVM.
set -euo pipefail

echo ""
echo "SignalPilot Firecracker Test"
echo "==========================="
echo ""

# Check KVM
if [ ! -e /dev/kvm ]; then
    echo "[FAIL] /dev/kvm not found!"
    echo "  Run with: docker run --rm -it --device /dev/kvm --privileged signalpilot/firecracker-test"
    exit 1
fi
echo "[OK] /dev/kvm found"
echo "[OK] Firecracker: $(firecracker --version 2>&1 | head -1)"

# Build ext4 rootfs from the directory tree (needs mount = needs runtime)
ROOTFS="/opt/rootfs.ext4"
ROOTFS_DIR="/opt/rootfs-tree"

if [ ! -f "${ROOTFS}" ]; then
    echo ""
    echo "[...] Building ext4 rootfs image..."

    # Calculate needed size (tree size + 64MB headroom)
    TREE_SIZE_KB=$(du -sk "${ROOTFS_DIR}" | cut -f1)
    SIZE_MB=$(( (TREE_SIZE_KB / 1024) + 64 ))

    dd if=/dev/zero of="${ROOTFS}" bs=1M count="${SIZE_MB}" 2>/dev/null
    mkfs.ext4 -F "${ROOTFS}" >/dev/null 2>&1

    MOUNT_DIR="/tmp/rootfs-mount"
    mkdir -p "${MOUNT_DIR}"
    mount "${ROOTFS}" "${MOUNT_DIR}"
    cp -a "${ROOTFS_DIR}"/* "${MOUNT_DIR}/"
    umount "${MOUNT_DIR}"
    rmdir "${MOUNT_DIR}"

    echo "[OK] Rootfs built: $(du -h ${ROOTFS} | cut -f1)"
fi

echo ""

# Run the boot test
exec python3 /opt/boot-vm.py
