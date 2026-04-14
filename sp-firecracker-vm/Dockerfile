# SignalPilot Firecracker Sandbox
# Universal Dockerfile — works on Linux, Windows 11 (WSL2), macOS (nested virt)
#
# REQUIRES: /dev/kvm available on host
#   Linux:   modprobe kvm (usually automatic)
#   Win11:   .wslconfig → nestedVirtualization=true
#   macOS:   Docker Desktop → nested virtualization enabled
#
# BUILD:
#   docker build -t signalpilot/sandbox .
#
# RUN:
#   docker run --device /dev/kvm --cap-add NET_ADMIN -p 8080:8080 signalpilot/sandbox

FROM ubuntu:22.04 AS base

ENV DEBIAN_FRONTEND=noninteractive
ENV FIRECRACKER_VERSION=1.10.1

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    iproute2 \
    iptables \
    python3 \
    python3-pip \
    python3-venv \
    e2fsprogs \
    && rm -rf /var/lib/apt/lists/*

# Install Firecracker + jailer
RUN ARCH=$(uname -m) && \
    curl -fsSL "https://github.com/firecracker-microvm/firecracker/releases/download/v${FIRECRACKER_VERSION}/firecracker-v${FIRECRACKER_VERSION}-${ARCH}.tgz" \
    | tar xz -C /tmp && \
    mv /tmp/release-v${FIRECRACKER_VERSION}-${ARCH}/firecracker-v${FIRECRACKER_VERSION}-${ARCH} /usr/local/bin/firecracker && \
    mv /tmp/release-v${FIRECRACKER_VERSION}-${ARCH}/jailer-v${FIRECRACKER_VERSION}-${ARCH} /usr/local/bin/jailer && \
    chmod +x /usr/local/bin/firecracker /usr/local/bin/jailer && \
    rm -rf /tmp/release-*

# Create working directories
RUN mkdir -p /opt/signalpilot/{kernel,rootfs,sockets,overlays}

# Copy kernel (prebuilt Firecracker-compatible kernel)
# Users can build their own or use AWS-published kernels
COPY kernel/vmlinux.bin /opt/signalpilot/kernel/

# Copy rootfs (Python sandbox environment as ext4 image)
COPY rootfs/sandbox-rootfs.ext4 /opt/signalpilot/rootfs/

# Install Python deps for sandbox manager
COPY pyproject.toml /opt/signalpilot/
RUN pip3 install --no-cache-dir /opt/signalpilot/

# Copy sandbox manager
COPY sandbox_manager.py /opt/signalpilot/
COPY executor_base.py /opt/signalpilot/
COPY executor_firecracker.py /opt/signalpilot/
COPY executor_gvisor.py /opt/signalpilot/
COPY scripts/setup-network.sh /opt/signalpilot/scripts/
RUN chmod +x /opt/signalpilot/scripts/setup-network.sh

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s \
    CMD curl -f http://localhost:8080/health || exit 1

ENTRYPOINT ["python3", "/opt/signalpilot/sandbox_manager.py"]
