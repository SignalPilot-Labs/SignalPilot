# SignalPilot Sandbox Setup (Win11)
#
# Run this script in PowerShell as Administrator.
# gVisor runs inside Docker Desktop (WSL2 backend). No nested virtualization needed.
#
# What it does:
#   1. Checks Windows version
#   2. Checks admin privileges
#   3. Ensures WSL is installed and up to date
#   4. Checks Docker Desktop is installed
#
# Usage:
#   Set-ExecutionPolicy Bypass -Scope Process
#   .\setup-windows.ps1

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  SignalPilot Sandbox Setup (Win11)     " -ForegroundColor Cyan
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

# ─── Step 3: Check/enable WSL ───────────────────────────────────────────────

$wslFeature = Get-WindowsOptionalFeature -Online -FeatureName "Microsoft-Windows-Subsystem-Linux" 2>$null
if ($wslFeature.State -ne "Enabled") {
    Write-Host "[...] Enabling WSL..." -ForegroundColor Yellow
    dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart | Out-Null
    $needsReboot = $true
} else {
    Write-Host "[OK] WSL enabled" -ForegroundColor Green
}

# ─── Step 4: Update WSL2 ────────────────────────────────────────────────────

Write-Host "[...] Updating WSL2 kernel..." -ForegroundColor Yellow
wsl --update 2>$null | Out-Null
Write-Host "[OK] WSL2 up to date" -ForegroundColor Green

# ─── Step 5: Check Docker ───────────────────────────────────────────────────

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
} else {
    Write-Host "Ready! Run:" -ForegroundColor Green
    Write-Host "  docker run --cap-add SYS_PTRACE --cap-add SYS_ADMIN signalpilot/sandbox" -ForegroundColor White
}

Write-Host ""
