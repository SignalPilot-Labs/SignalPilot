# Running Firecracker microVMs on Windows 11 via Docker

**Status:** Verified working
**Date:** March 31, 2026
**Test machine:** AMD Ryzen 9 9950X3D, Windows 11 Build 26200, Docker Desktop 27.5.1

---

## How it works

Firecracker requires KVM (Linux Kernel Virtual Machine). Windows 11 doesn't have KVM natively, but Docker Desktop runs a Linux VM via WSL2 under the hood. If you enable **nested virtualization** in WSL2, that Linux VM gets access to `/dev/kvm`, which you can then pass through to Docker containers.

```
Windows 11
  └── Hyper-V / Virtual Machine Platform
        └── WSL2 Linux VM (with KVM enabled via nestedVirtualization=true)
              └── Docker container (--device /dev/kvm)
                    └── Firecracker microVM (your sandbox)
```

---

## Prerequisites

| Requirement                  | Notes                                                                                                |
| ---------------------------- | ---------------------------------------------------------------------------------------------------- |
| Windows 11 (build 22000+)    | Required for WSL2 nested virtualization                                                              |
| CPU with AMD-V or Intel VT-x | All modern CPUs have this. Enabled by default on most builds; consumer laptops may need BIOS toggle. |
| Docker Desktop installed     | Must use WSL2 backend (default since Docker Desktop 4.x)                                             |
| x86_64 architecture          | ARM Windows (Snapdragon) is a separate target — not covered here                                     |

**If Docker Desktop is already running on your machine, prerequisites 1-3 are already met.** Docker Desktop requires WSL2 which requires virtualization support.

---

## One-time setup

### Step 1 — Create `.wslconfig` with nested virtualization

Open PowerShell (does **not** need to be admin) and run:

```powershell
notepad "$env:USERPROFILE\.wslconfig"
```

Add this content and save:

```ini
[wsl2]
nestedVirtualization=true
```

**Important:** Do NOT use PowerShell's `>` redirect to create this file — it writes UTF-16 which WSL can't read. Use Notepad, VS Code, or another text editor. If you must use the command line:

```powershell
# Safe way — writes UTF-8
[System.IO.File]::WriteAllText("$env:USERPROFILE\.wslconfig", "[wsl2]`nnestedVirtualization=true`n")
```

### Step 2 — Restart WSL

```powershell
wsl --shutdown
```

### Step 3 — Restart Docker Desktop

Open Docker Desktop and wait for it to fully start (green status in the system tray).

### Step 4 — Verify KVM is available

```powershell
# In PowerShell or Git Bash (note: MSYS_NO_PATHCONV=1 prevents Git Bash path mangling)
MSYS_NO_PATHCONV=1 docker run --rm --device /dev/kvm alpine ls -la /dev/kvm
```

Expected output:

```
crw-rw----    1 root     109        10, 232 ...  /dev/kvm
```

If you see this, your system is Firecracker-ready.

---

## Automated setup script

The script `scripts/setup-windows.ps1` automates all of the above:

```powershell
# Run in PowerShell as Administrator
Set-ExecutionPolicy Bypass -Scope Process
.\scripts\setup-windows.ps1
```

It will:

- Check Windows version
- Enable Virtual Machine Platform feature if needed
- Update WSL2 kernel
- Write `.wslconfig` with nested virtualization
- Restart WSL
- Verify `/dev/kvm` inside Docker

---

## Building the test container

```bash
cd sp-firecracker-vm

# Git Bash / MSYS users: MSYS_NO_PATHCONV=1 prevents path mangling
MSYS_NO_PATHCONV=1 docker build -f Dockerfile.test -t sp-firecracker-test .
```

Build time: ~2 minutes (downloads Firecracker binary + kernel, builds rootfs).

What the build does:

1. Installs Firecracker v1.10.1 binary + jailer
2. Downloads a prebuilt Firecracker-compatible Linux kernel from AWS S3
3. Builds a minimal rootfs directory tree (busybox + Python 3.10)

---

## Running the test

```bash
MSYS_NO_PATHCONV=1 docker run --rm --device /dev/kvm --privileged sp-firecracker-test
```

Expected output (abbreviated):

```
[OK] /dev/kvm found
[OK] Firecracker: Firecracker v1.10.1
[...] Building ext4 rootfs image...
[OK] Rootfs built: 55M

[OK] /dev/kvm available
[OK] Kernel: /opt/vmlinux.bin (20MB)
[OK] Rootfs: /opt/rootfs.ext4 (114MB)
[...] Starting Firecracker process...
[OK] Firecracker API socket ready
[...] Configuring VM...
  [OK] Kernel configured
  [OK] Rootfs configured
  [OK] Machine: 1 vCPU, 256MB RAM
[...] Booting microVM...
  [OK] VM started in 4ms

─── VM Serial Console Output ─────────────────────

============================================
  SignalPilot Firecracker VM - BOOT SUCCESS
============================================
Kernel: 4.14.174
{
  "status": "ok",
  "python": "3.10.12",
  "platform": "linux",
  "message": "Hello from inside a Firecracker microVM!"
}
============================================
  VM READY - Firecracker is working!
============================================

==================================================
  SUCCESS — Firecracker is working on your system!
==================================================
  Boot time: 4ms
```

---

## Flags explained

| Flag                | Why it's needed                                                                                                                                       |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--device /dev/kvm` | Passes the KVM device from WSL2 host into the container so Firecracker can create VMs                                                                 |
| `--privileged`      | Needed at runtime so the container can `mount` the ext4 rootfs image to populate it. In production this step is done at build time — see notes below. |

### Reducing `--privileged` in production

The test container uses `--privileged` only because it builds the ext4 rootfs image at runtime (requires `mount`). In the production sandbox container this is eliminated by pre-building the rootfs image during `docker build` on a Linux CI machine and `COPY`ing it in. The final production container only needs `--device /dev/kvm --cap-add NET_ADMIN`.

---

## How the Firecracker API works

Firecracker exposes a REST API over a Unix socket. The full VM lifecycle is ~10 API calls:

```python
# 1. Start firecracker process
subprocess.Popen(["firecracker", "--api-sock", "/tmp/fc.sock", "--log-path", "/tmp/fc.log"])

# 2. Configure kernel (via HTTP over Unix socket)
PUT /boot-source  { kernel_image_path, boot_args }

# 3. Configure rootfs
PUT /drives/rootfs  { path_on_host, is_root_device: true }

# 4. Configure resources
PUT /machine-config  { vcpu_count: 1, mem_size_mib: 512 }

# 5. (Optional) Configure vsock for host<->guest communication
PUT /vsock  { guest_cid: 3, uds_path: "/tmp/vsock.sock" }

# 6. Boot
PUT /actions  { action_type: "InstanceStart" }

# VM boots in ~125ms, runs code, exits
# Kill by terminating the firecracker process
```

The log file must be pre-created before starting Firecracker or it will exit with error code 1.

---

## Troubleshooting

### `/dev/kvm` not found inside the container

**Cause:** Nested virtualization not enabled or WSL/Docker not restarted after enabling it.

**Fix:**

1. Verify `.wslconfig` exists and contains `nestedVirtualization=true`
2. Run `wsl --shutdown` in PowerShell
3. Fully restart Docker Desktop (right-click tray icon → Quit, then relaunch)
4. Try again

### Path mangling in Git Bash

Git Bash on Windows converts Unix paths like `/dev/kvm` to Windows paths like `C:/dev/kvm`, which breaks Docker commands.

**Fix:** Prefix commands with `MSYS_NO_PATHCONV=1`:

```bash
MSYS_NO_PATHCONV=1 docker run --device /dev/kvm ...
```

### `.wslconfig` written as UTF-16 (garbled content)

PowerShell's `>` and `echo` operators write UTF-16. WSL silently fails to parse it.

**Symptoms:** `wsl --shutdown` + restart doesn't help, `/dev/kvm` still missing.

**Fix:** Check the file:

```bash
cat "C:/Users/<you>/.wslconfig"
# If you see spaces between every character (e . g . l i k e   t h i s) it's UTF-16
```

Recreate it correctly:

```powershell
[System.IO.File]::WriteAllText("$env:USERPROFILE\.wslconfig", "[wsl2]`nnestedVirtualization=true`n")
wsl --shutdown
# Restart Docker Desktop
```

### Firecracker exits with code 1 immediately

**Cause:** Log file path doesn't exist.

**Fix:** Pre-create the log file before starting Firecracker:

```python
open("/tmp/firecracker.log", "w").close()
subprocess.Popen(["firecracker", "--api-sock", "...", "--log-path", "/tmp/firecracker.log"])
```

### `mount: Operation not permitted` during Docker build

**Cause:** `docker build` runs without elevated privileges, so `mount` fails.

**Fix:** Move any step that requires `mount` (e.g., building an ext4 image) to container startup (`ENTRYPOINT`/`CMD`) rather than `RUN` in the Dockerfile. At runtime, pass `--privileged` or the specific `--cap-add` needed.

### Corporate / enterprise machines

Some enterprise IT policies block WSL2, Hyper-V, or nested virtualization via Group Policy. If the setup script fails with permission errors, an IT admin needs to whitelist these features. This is a policy decision outside our control — the fallback is `--sandbox-mode=container`.

---

## Platform support summary

| Platform                        | Firecracker supported? | Method                          | Notes                                                       |
| ------------------------------- | ---------------------- | ------------------------------- | ----------------------------------------------------------- |
| **Windows 11** (x86_64)         | ✅ Yes                 | WSL2 nested virtualization      | One-time `.wslconfig` setup                                 |
| **Windows 10**                  | ⚠️ Maybe               | WSL2 nested virt (build 19041+) | Less tested, older WSL2 kernels may not support nested KVM  |
| **Windows ARM** (Snapdragon)    | ❌ No                  | —                               | WSL2 ARM kernel doesn't expose KVM. Use container fallback. |
| **Linux** (bare metal)          | ✅ Yes                 | Native KVM                      | `--device /dev/kvm`, just works                             |
| **Linux** (VM with nested virt) | ✅ Yes                 | Nested KVM                      | Enable nested virt on host hypervisor                       |
| **macOS Apple Silicon** (M1+)   | ⚠️ Experimental        | Docker Desktop nested virt      | macOS 13+, Docker Desktop 4.30+. Less proven.               |
| **macOS Intel**                 | ⚠️ Unlikely            | —                               | Dying platform, not worth optimizing                        |

---

## Files in this directory

```
sp-firecracker-vm/
├── Dockerfile                  # Production sandbox container
├── Dockerfile.test             # Self-contained test container (downloads everything)
├── Dockerfile.rootfs           # Builds the Python sandbox ext4 rootfs image
├── docker-compose.yml          # Local mode deployment
├── sandbox_manager.py          # HTTP API that manages Firecracker VM lifecycle
├── signalpilot-sandbox.yml     # Sandbox mode config (local/cloud/container)
├── windows-instructions.md     # This file
├── kernel/                     # Place vmlinux.bin here for production builds
├── rootfs/
│   └── sandbox_agent.py        # Runs inside the microVM, handles code execution
└── scripts/
    ├── setup-windows.ps1       # Automated Windows 11 setup
    ├── setup-macos.sh          # macOS setup and checks
    ├── setup-linux.sh          # Linux setup (loads KVM module)
    ├── setup-network.sh        # TAP networking + iptables for gateway-only access
    └── build-test-rootfs.sh    # Builds minimal rootfs directory tree
```
