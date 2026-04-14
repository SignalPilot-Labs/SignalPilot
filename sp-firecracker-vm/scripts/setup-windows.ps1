# SignalPilot Firecracker Setup — Windows 11
#
# Run this script in PowerShell as Administrator.
# It enables everything needed to run Firecracker inside Docker on Windows 11.
#
# What it does:
#   1. Checks CPU virtualization support
#   2. Ensures WSL2 is installed and up to date
#   3. Enables nested virtualization in .wslconfig
#   4. Restarts WSL
#   5. Verifies /dev/kvm is available
#
# Usage:
#   Set-ExecutionPolicy Bypass -Scope Process
#   .\setup-windows.ps1

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  SignalPilot Firecracker Setup (Win11) " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ─── Step 1: Check Windows version ──────────────────────────────────────────

$build = [System.Environment]::OSVersion.Version.Build
if ($build -lt 22000) {
    Write-Host "[FAIL] Windows 11 required (build 22000+). You have build $build." -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Windows 11 (build $build)" -ForegroundColor Green

# ─── Step 2: Check if running as admin ───────────────────────────────────────

$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "[WARN] Not running as Administrator. Some steps may fail." -ForegroundColor Yellow
    Write-Host "       Re-run with: Start-Process powershell -Verb RunAs" -ForegroundColor Yellow
}

# ─── Step 3: Check/enable Virtual Machine Platform ──────────────────────────

$vmpFeature = Get-WindowsOptionalFeature -Online -FeatureName "VirtualMachinePlatform" 2>$null
if ($vmpFeature.State -ne "Enabled") {
    Write-Host "[...] Enabling Virtual Machine Platform..." -ForegroundColor Yellow
    dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart | Out-Null
    $needsReboot = $true
} else {
    Write-Host "[OK] Virtual Machine Platform enabled" -ForegroundColor Green
}

# ─── Step 4: Check/enable WSL ───────────────────────────────────────────────

$wslFeature = Get-WindowsOptionalFeature -Online -FeatureName "Microsoft-Windows-Subsystem-Linux" 2>$null
if ($wslFeature.State -ne "Enabled") {
    Write-Host "[...] Enabling WSL..." -ForegroundColor Yellow
    dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart | Out-Null
    $needsReboot = $true
} else {
    Write-Host "[OK] WSL enabled" -ForegroundColor Green
}

# ─── Step 5: Update WSL2 ────────────────────────────────────────────────────

Write-Host "[...] Updating WSL2 kernel..." -ForegroundColor Yellow
wsl --update 2>$null | Out-Null
Write-Host "[OK] WSL2 up to date" -ForegroundColor Green

# ─── Step 6: Enable nested virtualization ────────────────────────────────────

$wslConfigPath = "$env:USERPROFILE\.wslconfig"
$nestedEnabled = $false

if (Test-Path $wslConfigPath) {
    $content = Get-Content $wslConfigPath -Raw
    if ($content -match "nestedVirtualization\s*=\s*true") {
        $nestedEnabled = $true
        Write-Host "[OK] Nested virtualization already enabled in .wslconfig" -ForegroundColor Green
    }
}

if (-not $nestedEnabled) {
    Write-Host "[...] Enabling nested virtualization in .wslconfig..." -ForegroundColor Yellow

    if (Test-Path $wslConfigPath) {
        $content = Get-Content $wslConfigPath -Raw
        if ($content -match "\[wsl2\]") {
            # [wsl2] section exists, add under it
            $content = $content -replace "(\[wsl2\])", "`$1`nnestedVirtualization=true"
        } else {
            # No [wsl2] section, append it
            $content += "`n[wsl2]`nnestedVirtualization=true`n"
        }
        Set-Content $wslConfigPath $content
    } else {
        # Create new file
        @"
[wsl2]
nestedVirtualization=true
"@ | Set-Content $wslConfigPath
    }

    Write-Host "[OK] Nested virtualization enabled" -ForegroundColor Green
    $needsWslRestart = $true
}

# ─── Step 7: Restart WSL if needed ──────────────────────────────────────────

if ($needsWslRestart) {
    Write-Host "[...] Restarting WSL..." -ForegroundColor Yellow
    wsl --shutdown
    Start-Sleep -Seconds 2
    Write-Host "[OK] WSL restarted" -ForegroundColor Green
}

# ─── Step 8: Verify /dev/kvm ────────────────────────────────────────────────

Write-Host "[...] Checking /dev/kvm availability..." -ForegroundColor Yellow
$kvmCheck = wsl -e sh -c "ls /dev/kvm 2>/dev/null && echo 'KVM_OK' || echo 'KVM_MISSING'" 2>$null
if ($kvmCheck -match "KVM_OK") {
    Write-Host "[OK] /dev/kvm is available — Firecracker ready!" -ForegroundColor Green
} else {
    Write-Host "[WARN] /dev/kvm not found." -ForegroundColor Yellow
    Write-Host "       Try: restart Docker Desktop, then run this script again." -ForegroundColor Yellow
    if ($needsReboot) {
        Write-Host "       A Windows reboot is required first (features were just enabled)." -ForegroundColor Yellow
    }
}

# ─── Step 9: Check Docker ───────────────────────────────────────────────────

$dockerVersion = docker --version 2>$null
if ($dockerVersion) {
    Write-Host "[OK] Docker: $dockerVersion" -ForegroundColor Green
} else {
    Write-Host "[WARN] Docker not found. Install Docker Desktop from docker.com" -ForegroundColor Yellow
}

# ─── Summary ─────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Setup Summary" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

if ($needsReboot) {
    Write-Host "ACTION REQUIRED: Reboot Windows, then:" -ForegroundColor Yellow
    Write-Host "  1. Open Docker Desktop" -ForegroundColor Yellow
    Write-Host "  2. Run this script again to verify" -ForegroundColor Yellow
} elseif ($needsWslRestart) {
    Write-Host "ACTION REQUIRED: Restart Docker Desktop, then:" -ForegroundColor Yellow
    Write-Host "  docker run --device /dev/kvm signalpilot/sandbox" -ForegroundColor White
} else {
    Write-Host "Ready! Run:" -ForegroundColor Green
    Write-Host "  docker run --device /dev/kvm signalpilot/sandbox" -ForegroundColor White
}

Write-Host ""
