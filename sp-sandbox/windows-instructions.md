# Running SignalPilot Sandbox on Windows 11 via Docker
**Status:** Verified working
**Date:** March 31, 2026
**Test machine:** AMD Ryzen 9 9950X3D, Windows 11 Build 26200, Docker Desktop 27.5.1

---

## How it works

The SignalPilot sandbox uses gVisor (runsc) for isolation. gVisor runs entirely in user space and does not require KVM or nested virtualization. It works wherever Docker runs.

```
Windows 11
  └── WSL2 Linux VM
        └── Docker container (--cap-add SYS_PTRACE --cap-add SYS_ADMIN)
              └── gVisor sandbox (your isolated execution environment)
```

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Windows 11 (build 22000+) | Required for WSL2 |
| Docker Desktop installed | Must use WSL2 backend (default since Docker Desktop 4.x) |
| x86_64 or ARM64 architecture | gVisor supports both |

**If Docker Desktop is already running on your machine, all prerequisites are met.**

---

## One-time setup

### Step 1 — Install Docker Desktop

Download from [docker.com](https://www.docker.com/products/docker-desktop/). Ensure the WSL2 backend is enabled (this is the default).

### Step 2 — Restart Docker Desktop

Open Docker Desktop and wait for it to fully start (green status in the system tray).

### Step 3 — Verify Docker is working

```powershell
docker run --rm hello-world
```

---

## Automated setup script

The script `scripts/setup-windows.ps1` checks all prerequisites:

```powershell
# Run in PowerShell as Administrator
Set-ExecutionPolicy Bypass -Scope Process
.\scripts\setup-windows.ps1
```

It will:
- Check Windows version
- Ensure WSL is installed and up to date
- Check Docker Desktop is installed

---

## Building the test container

```bash
cd sp-sandbox

# Git Bash / MSYS users: MSYS_NO_PATHCONV=1 prevents path mangling
MSYS_NO_PATHCONV=1 docker build -f Dockerfile.test -t signalpilot/sandbox-test .
```

Build time: ~30 seconds (downloads gVisor runsc binary only).

What the build does:
1. Installs gVisor runsc binary (pinned version 20260323.0)

---

## Running the test

```bash
docker run --rm --cap-add SYS_PTRACE --cap-add SYS_ADMIN signalpilot/sandbox-test
```

Expected output:
```
SignalPilot Sandbox Test -- gVisor
===================================

[OK] runsc: runsc version 20260323.0
[...] Running gVisor sandbox test...
gVisor sandbox working
[OK] gVisor sandbox is working on your system!
```

---

## Flags explained

| Flag | Why it's needed |
|------|----------------|
| `--cap-add SYS_PTRACE` | Required by gVisor (runsc) to intercept system calls |
| `--cap-add SYS_ADMIN` | Required by gVisor (runsc) for namespace setup |

No device passthrough or `--privileged` flag required.

---

## Troubleshooting

### `permission denied` running runsc

**Cause:** Missing capabilities.

**Fix:** Ensure you are passing `--cap-add SYS_PTRACE --cap-add SYS_ADMIN` to Docker run.

### Path mangling in Git Bash

Git Bash on Windows converts Unix paths to Windows paths, which can break Docker commands.

**Fix:** Prefix commands with `MSYS_NO_PATHCONV=1`:
```bash
MSYS_NO_PATHCONV=1 docker run --cap-add SYS_PTRACE ...
```

### Corporate / enterprise machines

Some enterprise IT policies block WSL2 or Docker Desktop via Group Policy. If the setup script fails with permission errors, an IT admin needs to whitelist these features.

---

## Platform support summary

| Platform | gVisor sandbox supported? | Method | Notes |
|----------|--------------------------|--------|-------|
| **Windows 11** (x86_64) | Yes | Docker Desktop (WSL2 backend) | No KVM or nested virtualization needed |
| **Windows 10** | Yes | Docker Desktop (WSL2 backend) | Build 19041+ required for WSL2 |
| **Windows ARM** (Snapdragon) | Yes | Docker Desktop (WSL2 backend) | gVisor supports ARM64 |
| **Linux** (bare metal) | Yes | Docker | Native, works out of the box |
| **Linux** (VM) | Yes | Docker | No nested virtualization needed |
| **macOS Apple Silicon** (M1+) | Yes | Docker Desktop | Works without any special configuration |
| **macOS Intel** | Yes | Docker Desktop | Works without any special configuration |

---

## Files in this directory

```
sp-sandbox/
├── Dockerfile                  # Production sandbox container (gVisor)
├── Dockerfile.sandbox          # Sandbox manager container
├── Dockerfile.test             # Self-contained test container
├── sandbox_manager.py          # HTTP API that manages gVisor sandbox lifecycle
├── executor_base.py            # Base executor interface
├── executor_gvisor.py          # gVisor (runsc) executor implementation
├── windows-instructions.md     # This file
└── scripts/
    ├── setup-windows.ps1       # Automated Windows 11 setup
    ├── setup-macos.sh          # macOS setup and checks
    └── setup-linux.sh          # Linux setup
```
