#!/bin/sh
# SignalPilot Installer v0.1.0
# https://github.com/SignalPilot-Labs/SignalPilot

set -e

# ─────────────────────────────────────────────────────────────────────────────
# Flags
# ─────────────────────────────────────────────────────────────────────────────

SKIP_BUILD=0
DEV_MODE=0
NO_COLOR=0
SHOW_HELP=0

for arg in "$@"; do
  case "$arg" in
    --skip-build) SKIP_BUILD=1 ;;
    --dev)        DEV_MODE=1 ;;
    --no-color)   NO_COLOR=1 ;;
    --help|-h)    SHOW_HELP=1 ;;
  esac
done

# ─────────────────────────────────────────────────────────────────────────────
# ANSI helpers
# ─────────────────────────────────────────────────────────────────────────────

if [ "$NO_COLOR" = "1" ] || [ ! -t 1 ]; then
  BOLD=""  DIM=""  GREEN=""  RESET=""
else
  BOLD="\033[1m"
  DIM="\033[2m"
  GREEN="\033[32m"
  RESET="\033[0m"
fi

bold() { printf "${BOLD}%s${RESET}" "$1"; }
dim()  { printf "${DIM}%s${RESET}" "$1"; }

# ─────────────────────────────────────────────────────────────────────────────
# Layout helpers
# ─────────────────────────────────────────────────────────────────────────────

print_header() {
  printf "\n"
  printf "  ┌───────────────────────────────────────────┐\n"
  printf "  │                                           │\n"
  printf "  │          s i g n a l p i l o t            │\n"
  printf "  │                                           │\n"
  printf "  │          Install  v0.1.0                  │\n"
  printf "  │                                           │\n"
  printf "  └───────────────────────────────────────────┘\n"
  printf "\n"
}

print_section() {
  # $1 = title, $2 = step number (e.g. "1"), $3 = total steps (e.g. "7")
  if [ -n "$2" ] && [ -n "$3" ]; then
    printf "\n  ${BOLD}%s${RESET}  ${DIM}[%s/%s]${RESET}\n\n" "$1" "$2" "$3"
  else
    printf "\n  ${BOLD}%s${RESET}\n\n" "$1"
  fi
}

# print_kv <key> <value>  — left-padded, key fixed at 20 chars
print_kv() {
  printf "    %-20s%s\n" "$1" "$2"
}

# print_check <label> <detail>
print_check() {
  printf "    %-18s${GREEN}✓${RESET}  %s\n" "$1" "$2"
}

# print_fail <label> <detail>
print_fail() {
  printf "    %-18s✗  %s\n" "$1" "$2"
}

# print_wait <label> <detail>
print_wait() {
  printf "    %-18s${DIM}◐${RESET}  %s\n" "$1" "$2"
}

# print_dot <label> <detail>
print_dot() {
  printf "    %-18s${DIM}·${RESET}  %s\n" "$1" "$2"
}

# ─────────────────────────────────────────────────────────────────────────────
# Spinner
# ─────────────────────────────────────────────────────────────────────────────

SPINNER_PID=""

spinner_start() {
  # $1 = message
  _sp_msg="$1"
  ( i=0
    frames="◒ ◐ ◓ ◑"
    while true; do
      for f in $frames; do
        printf "\r  ${DIM}%s${RESET}  %s " "$f" "$_sp_msg"
        sleep 0.12
      done
    done
  ) &
  SPINNER_PID=$!
}

spinner_stop() {
  if [ -n "$SPINNER_PID" ]; then
    kill "$SPINNER_PID" 2>/dev/null
    wait "$SPINNER_PID" 2>/dev/null
    SPINNER_PID=""
    printf "\r\033[2K"
  fi
}

# ─────────────────────────────────────────────────────────────────────────────
# Input prompts
# ─────────────────────────────────────────────────────────────────────────────

prompt_input() {
  # $1 = label; stores result in REPLY
  printf "    %s: " "$(bold "$1")"
  read -r REPLY
}

prompt_secret() {
  # $1 = label; stores result in REPLY
  printf "    %s: " "$(bold "$1")"
  stty -echo 2>/dev/null || true
  read -r REPLY
  stty echo 2>/dev/null || true
  printf "\n"
}

prompt_yn() {
  # $1 = question, returns 0 for yes, 1 for no
  printf "    %s ${DIM}[y/N]${RESET} " "$1"
  read -r _yn
  case "$_yn" in
    [Yy]*) return 0 ;;
    *)     return 1 ;;
  esac
}

# ─────────────────────────────────────────────────────────────────────────────
# Dependency checks
# ─────────────────────────────────────────────────────────────────────────────

check_command() {
  # $1 = command to test, $2 = version flag (default --version)
  _vflag="${2:---version}"
  if command -v "$1" >/dev/null 2>&1; then
    _ver=$(command "$1" "$_vflag" 2>&1 | head -1 | sed 's/[^0-9.]*\([0-9][0-9.]*\).*/\1/')
    printf "%s" "$_ver"
    return 0
  fi
  return 1
}

check_port() {
  # $1 = port number; returns 0 if available, 1 if in use
  if command -v ss >/dev/null 2>&1; then
    ss -tln 2>/dev/null | awk '{print $4}' | grep -q ":$1$" && return 1
  elif command -v netstat >/dev/null 2>&1; then
    netstat -tln 2>/dev/null | awk '{print $4}' | grep -q ":$1$" && return 1
  elif command -v lsof >/dev/null 2>&1; then
    lsof -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1 && return 1
  fi
  return 0
}

port_owner() {
  # $1 = port; print process name using it
  if command -v lsof >/dev/null 2>&1; then
    lsof -iTCP:"$1" -sTCP:LISTEN -n -P 2>/dev/null | awk 'NR==2{print $1}' || true
  fi
}

# ─────────────────────────────────────────────────────────────────────────────
# Platform detection
# ─────────────────────────────────────────────────────────────────────────────

detect_platform() {
  _kernel=$(uname -s)
  _arch=$(uname -m)

  # Normalise arch
  case "$_arch" in
    x86_64)  ARCH="x86_64" ;;
    aarch64|arm64) ARCH="arm64" ;;
    *)       ARCH="$_arch" ;;
  esac

  # Detect WSL
  if [ -f /proc/version ] && grep -qi microsoft /proc/version 2>/dev/null; then
    OS="WSL2"
    OS_PRETTY="Linux (WSL2, ${ARCH})"
    DOCKER_URL="https://docs.docker.com/desktop/setup/install/windows-install/"
    OPEN_CMD="explorer.exe"
  elif [ "$_kernel" = "Darwin" ]; then
    OS="macOS"
    _macos_ver=$(sw_vers -productVersion 2>/dev/null || echo "")
    OS_PRETTY="macOS ${_macos_ver} (${ARCH})"
    DOCKER_URL="https://docs.docker.com/desktop/setup/install/mac-install/"
    OPEN_CMD="open"
  else
    OS="Linux"
    if [ -f /etc/os-release ]; then
      _distro=$(. /etc/os-release && printf "%s" "$PRETTY_NAME")
    else
      _distro="Linux"
    fi
    OS_PRETTY="${_distro} (${ARCH})"
    DOCKER_URL="https://docs.docker.com/desktop/setup/install/linux/"
    OPEN_CMD="xdg-open"
  fi

  # Shell
  SHELL_NAME=$(basename "${SHELL:-unknown}")
  SHELL_VER=$(command "$SHELL_NAME" --version 2>&1 | head -1 | sed 's/[^0-9.]*\([0-9][0-9.]*\).*/\1/' || echo "")
  SHELL_PRETTY="${SHELL_NAME} ${SHELL_VER}"

  CURRENT_USER=$(id -un)
}

# ─────────────────────────────────────────────────────────────────────────────
# Docker checks
# ─────────────────────────────────────────────────────────────────────────────

check_docker() {
  DOCKER_OK=0
  DOCKER_RUNNING=0
  DOCKER_VER=""
  COMPOSE_OK=0
  COMPOSE_VER=""

  if command -v docker >/dev/null 2>&1; then
    DOCKER_VER=$(docker --version 2>/dev/null | sed 's/[^0-9.]*\([0-9][0-9.]*\).*/\1/' || echo "")
    DOCKER_OK=1

    # Check daemon
    if docker info >/dev/null 2>&1; then
      DOCKER_RUNNING=1
    fi

    # Check compose v2 plugin
    if docker compose version >/dev/null 2>&1; then
      COMPOSE_VER=$(docker compose version 2>/dev/null | sed 's/[^0-9.]*\([0-9][0-9.]*\).*/\1/' || echo "")
      COMPOSE_OK=1
    fi
  fi
}

prompt_docker_install() {
  printf "\n"
  printf "  ${BOLD}Docker Desktop is required to run SignalPilot.${RESET}\n\n"
  printf "  Download URL:\n"
  printf "    ${BOLD}%s${RESET}\n\n" "$DOCKER_URL"

  if prompt_yn "Open the download page now?"; then
    "$OPEN_CMD" "$DOCKER_URL" 2>/dev/null || true
  fi

  printf "\n  ${DIM}Install Docker Desktop, then press Enter to continue...${RESET}"
  read -r _ignored
}

wait_for_docker() {
  printf "\n  ${DIM}Waiting for Docker daemon to start${RESET}"
  _attempts=0
  while [ $_attempts -lt 30 ]; do
    if docker info >/dev/null 2>&1; then
      printf "\n"
      return 0
    fi
    printf "."
    sleep 2
    _attempts=$((_attempts + 1))
  done
  printf "\n"
  return 1
}

# ─────────────────────────────────────────────────────────────────────────────
# .env configuration
# ─────────────────────────────────────────────────────────────────────────────

configure_env() {
  _env_file="${REPO_DIR}/.env"
  _example_file="${REPO_DIR}/.env.example"

  if [ -f "$_env_file" ]; then
    print_section "Configuration" "$STEP" "$TOTAL_STEPS"
    print_check ".env" "already exists, skipping"
    return
  fi

  print_section "Configuration" "$STEP" "$TOTAL_STEPS"

  if [ -f "$_example_file" ]; then
    cp "$_example_file" "$_env_file"
  fi

  if ! prompt_yn "Configure environment now?"; then
    printf "\n    ${DIM}Skipped — edit %s before starting services.${RESET}\n" "$_env_file"
    return
  fi

  printf "\n"
  prompt_input "GitHub repo (e.g. YourOrg/SignalPilot)"
  GITHUB_REPO="$REPLY"
  prompt_secret "GitHub token (GIT_TOKEN)"
  GIT_TOKEN="$REPLY"
  prompt_secret "Claude OAuth token (CLAUDE_CODE_OAUTH_TOKEN)"
  CLAUDE_CODE_OAUTH_TOKEN="$REPLY"
  printf "\n"

  # Mask display — only show last 4 chars if token is long enough
  _mask() {
    _len=$(printf "%s" "$1" | wc -c)
    if [ "$_len" -gt 8 ]; then
      printf "****%s" "$(printf "%s" "$1" | tail -c 4)"
    else
      printf "****"
    fi
  }

  print_check "GITHUB_REPO" "$GITHUB_REPO"
  if [ -n "$GIT_TOKEN" ]; then
    print_check "GIT_TOKEN" "$(_mask "$GIT_TOKEN")"
  fi
  if [ -n "$CLAUDE_CODE_OAUTH_TOKEN" ]; then
    print_check "CLAUDE_CODE_OAUTH_TOKEN" "$(_mask "$CLAUDE_CODE_OAUTH_TOKEN")"
  fi

  # Write values line-by-line (avoids sed injection with special chars)
  _write_env_key() {
    # $1 = key, $2 = value, $3 = file
    grep -v "^$1=" "$3" > "${3}.tmp" 2>/dev/null || true
    printf "%s=%s\n" "$1" "$2" >> "${3}.tmp"
    mv "${3}.tmp" "$3"
  }

  if [ -n "$GITHUB_REPO" ]; then
    _write_env_key "GITHUB_REPO" "$GITHUB_REPO" "$_env_file"
  fi
  if [ -n "$GIT_TOKEN" ]; then
    _write_env_key "GIT_TOKEN" "$GIT_TOKEN" "$_env_file"
  fi
  if [ -n "$CLAUDE_CODE_OAUTH_TOKEN" ]; then
    _write_env_key "CLAUDE_CODE_OAUTH_TOKEN" "$CLAUDE_CODE_OAUTH_TOKEN" "$_env_file"
  fi

  # Restrict permissions — file contains secrets
  chmod 600 "$_env_file"

  printf "\n    ${DIM}Written to %s${RESET}\n" "$_env_file"
}

# ─────────────────────────────────────────────────────────────────────────────
# Cleanup on interrupt
# ─────────────────────────────────────────────────────────────────────────────

cleanup() {
  spinner_stop
  printf "\n\n  ${DIM}Installation cancelled.${RESET}\n\n"
  exit 130
}

trap cleanup INT TERM

# ─────────────────────────────────────────────────────────────────────────────
# Help
# ─────────────────────────────────────────────────────────────────────────────

if [ "$SHOW_HELP" = "1" ]; then
  printf "\n  ${BOLD}SignalPilot Installer${RESET}\n\n"
  printf "  Usage:  ./install.sh [flags]\n\n"
  printf "  Flags:\n"
  printf "    --skip-build    Skip Docker build step\n"
  printf "    --dev           Use docker-compose.dev.yml\n"
  printf "    --no-color      Disable ANSI color codes\n"
  printf "    --help          Show this help\n\n"
  exit 0
fi

# ─────────────────────────────────────────────────────────────────────────────
# Detect repo location
# ─────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR=$(cd "$(dirname "$0")" 2>/dev/null && pwd || pwd)
RUNNING_FROM_REPO=0

if [ -f "${SCRIPT_DIR}/install.sh" ] && [ -f "${SCRIPT_DIR}/.env.example" ]; then
  RUNNING_FROM_REPO=1
  REPO_DIR="$SCRIPT_DIR"
else
  REPO_DIR="${HOME}/.signalpilot"
fi

COMPOSE_DIR="${REPO_DIR}/signalpilot/docker"
if [ "$DEV_MODE" = "1" ]; then
  COMPOSE_FILE="${COMPOSE_DIR}/docker-compose.dev.yml"
else
  COMPOSE_FILE="${COMPOSE_DIR}/docker-compose.yml"
fi

STEP=0
if [ "$RUNNING_FROM_REPO" = "0" ]; then
  TOTAL_STEPS=7
else
  TOTAL_STEPS=6
fi

next_step() {
  STEP=$((STEP + 1))
}

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

print_header

# ── Platform ──────────────────────────────────────────────────────────────────

detect_platform

next_step
print_section "System" "$STEP" "$TOTAL_STEPS"
print_kv "OS"    "$OS_PRETTY"
print_kv "Shell" "$SHELL_PRETTY"
print_kv "User"  "$CURRENT_USER"

# ── Dependencies ──────────────────────────────────────────────────────────────

next_step
print_section "Dependencies" "$STEP" "$TOTAL_STEPS"

# Docker (with retry loop)
while true; do
  check_docker

  if [ "$DOCKER_OK" = "0" ]; then
    print_fail "Docker Desktop" "not found"
    prompt_docker_install
    continue
  fi

  if [ "$DOCKER_RUNNING" = "0" ]; then
    print_fail "Docker Desktop" "installed but not running"
    printf "\n  ${DIM}Please start Docker Desktop, then press Enter...${RESET}"
    read -r _ignored
    printf "\n"

    if wait_for_docker; then
      check_docker
    fi

    if [ "$DOCKER_RUNNING" = "0" ]; then
      printf "\n  Docker daemon still unreachable.\n"
      if [ "$OS" = "WSL2" ]; then
        printf "  ${DIM}Tip: Enable 'WSL Integration' in Docker Desktop → Settings → Resources → WSL Integration.${RESET}\n\n"
      fi
      printf "  Press Enter to retry, or Ctrl+C to exit.\n"
      read -r _ignored
      continue
    fi
  fi

  break
done

print_check "Docker Desktop" "v${DOCKER_VER}"

if [ "$COMPOSE_OK" = "1" ]; then
  print_check "Docker Compose" "v${COMPOSE_VER}"
else
  print_fail "Docker Compose" "docker compose plugin not found"
  printf "\n  ${DIM}Run: docker compose version — to verify your Docker Desktop install.${RESET}\n\n"
  exit 1
fi

# Git
GIT_VER=$(check_command git 2>/dev/null) && GIT_OK=1 || GIT_OK=0
if [ "$GIT_OK" = "1" ]; then
  print_check "Git" "v${GIT_VER}"
else
  print_fail "Git" "not found"
  printf "\n  ${DIM}Install git from https://git-scm.com/downloads${RESET}\n\n"
  exit 1
fi

# Ports
PORTS_FAIL=0
for port in 3200 3300 3400 3401 5600; do
  if check_port "$port"; then
    print_check "Port ${port}" "available"
  else
    _owner=$(port_owner "$port")
    if [ -n "$_owner" ]; then
      print_fail "Port ${port}" "in use by ${_owner}"
    else
      print_fail "Port ${port}" "in use"
    fi
    PORTS_FAIL=1
  fi
done

if [ "$PORTS_FAIL" = "1" ]; then
  printf "\n  ${DIM}Stop the processes using those ports and re-run the installer.${RESET}\n\n"
  exit 1
fi

# ── Clone (if not running from repo) ─────────────────────────────────────────

if [ "$RUNNING_FROM_REPO" = "0" ]; then
  next_step
  print_section "Cloning" "$STEP" "$TOTAL_STEPS"

  CLONE_URL="https://github.com/SignalPilot-Labs/SignalPilot.git"

  if [ -d "$REPO_DIR/.git" ]; then
    print_check "Repository" "already cloned at ${REPO_DIR}"
  else
    print_wait "Repository" "cloning..."
    spinner_start "Cloning SignalPilot"
    if git clone --depth 1 "$CLONE_URL" "$REPO_DIR" >/dev/null 2>&1; then
      spinner_stop
      print_check "Repository" "cloned to ${REPO_DIR}"
    else
      spinner_stop
      print_fail "Repository" "clone failed"
      printf "\n  ${DIM}Check your network connection and that you have access to the repo.${RESET}\n\n"
      exit 1
    fi
  fi
fi

# ── Configuration ─────────────────────────────────────────────────────────────

next_step
configure_env

# ── Build ─────────────────────────────────────────────────────────────────────

next_step
if [ "$SKIP_BUILD" = "1" ]; then
  print_section "Building" "$STEP" "$TOTAL_STEPS"
  printf "    ${DIM}Skipped (--skip-build)${RESET}\n"
else
  print_section "Building" "$STEP" "$TOTAL_STEPS"

  if [ ! -f "$COMPOSE_FILE" ]; then
    printf "  ${DIM}Compose file not found: %s${RESET}\n\n" "$COMPOSE_FILE"
    exit 1
  fi

  SERVICES="gateway web postgres sandbox"

  for svc in $SERVICES; do
    print_dot "$svc" "${DIM}queued${RESET}"
  done

  # Move cursor up to overwrite the dots
  _num_services=4
  printf "\033[%dA" "$_num_services"

  for svc in $SERVICES; do
    # Overwrite current line with spinner state
    printf "\033[2K"
    _build_start=$(date +%s)

    if [ "$svc" = "postgres" ]; then
      print_wait "$svc" "pulling..."
    else
      print_wait "$svc" "building..."
    fi

    _build_log=$(mktemp)

    if [ "$svc" = "postgres" ]; then
      # postgres is a pulled image, not built
      docker compose -f "$COMPOSE_FILE" pull postgres >"$_build_log" 2>&1
      _rc=$?
    else
      docker compose -f "$COMPOSE_FILE" build "$svc" >"$_build_log" 2>&1
      _rc=$?
    fi

    _build_end=$(date +%s)
    _build_elapsed=$((_build_end - _build_start))

    # Move up one line to overwrite
    printf "\033[1A\033[2K"

    if [ "$_rc" = "0" ]; then
      if [ "$svc" = "postgres" ]; then
        print_check "$svc" "pulled     ${DIM}${_build_elapsed}s${RESET}"
      else
        print_check "$svc" "built      ${DIM}${_build_elapsed}s${RESET}"
      fi
    else
      print_fail "$svc" "build failed"
      printf "\n  Build output:\n\n"
      sed 's/^/    /' "$_build_log" | tail -30
      rm -f "$_build_log"
      printf "\n  ${DIM}Run with --skip-build to skip this step after fixing the error.${RESET}\n\n"
      exit 1
    fi

    rm -f "$_build_log"
  done
fi

# ── Start services ────────────────────────────────────────────────────────────

next_step
print_section "Starting services" "$STEP" "$TOTAL_STEPS"

if ! docker compose -f "$COMPOSE_FILE" up -d >/dev/null 2>&1; then
  printf "  ${DIM}Failed to start services. Run:${RESET}\n"
  printf "    docker compose -f %s up\n\n" "$COMPOSE_FILE"
  exit 1
fi

# Wait for health checks
_wait_healthy() {
  # $1 = service name, $2 = max seconds
  _svc="$1"
  _max="${2:-60}"
  _i=0
  while [ "$_i" -lt "$_max" ]; do
    _state=$(docker compose -f "$COMPOSE_FILE" ps --format json "$_svc" 2>/dev/null \
      | tr ',' '\n' | grep -i health | head -1 | sed 's/.*:"\([^"]*\)".*/\1/')
    case "$_state" in
      healthy|running) return 0 ;;
    esac
    sleep 2
    _i=$((_i + 2))
  done
  return 1
}

for svc in postgres gateway web; do
  print_wait "$svc" "starting..."
  spinner_start "waiting for $svc"

  if _wait_healthy "$svc" 90; then
    spinner_stop
    printf "\033[1A\033[2K"
    case "$svc" in
      postgres) print_check "$svc" "healthy    (localhost:5600)" ;;
      gateway)  print_check "$svc" "healthy    (localhost:3300)" ;;
      web)      print_check "$svc" "ready      (localhost:3200)" ;;
    esac
  else
    spinner_stop
    printf "\033[1A\033[2K"
    print_fail "$svc" "did not become healthy in time"
    printf "\n  ${DIM}Check logs: docker compose -f %s logs %s${RESET}\n\n" "$COMPOSE_FILE" "$svc"
  fi
done

# ── Verify ───────────────────────────────────────────────────────────────────

next_step
print_section "Verifying" "$STEP" "$TOTAL_STEPS"

# verify_endpoint <label> <url> <expected_status>
verify_endpoint() {
  _ve_label="$1"
  _ve_url="$2"
  _ve_expect="${3:-200}"

  _ve_start=$(date +%s%N 2>/dev/null || date +%s)

  if command -v curl >/dev/null 2>&1; then
    _ve_code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 10 "$_ve_url" 2>/dev/null)
  elif command -v wget >/dev/null 2>&1; then
    _ve_code=$(wget -q --spider --server-response --timeout=10 "$_ve_url" 2>&1 | awk '/HTTP/{print $2}' | tail -1)
  else
    print_fail "$_ve_label" "no curl or wget available"
    return
  fi

  _ve_end=$(date +%s%N 2>/dev/null || date +%s)

  # Calculate ms (fallback to seconds if %N not supported)
  if echo "$_ve_start" | grep -q "N$"; then
    # %N not supported, use seconds
    _ve_ms="—"
  else
    _ve_ms=$(( (_ve_end - _ve_start) / 1000000 ))
    _ve_ms="${_ve_ms}ms"
  fi

  if [ "$_ve_code" = "$_ve_expect" ]; then
    print_check "$_ve_label" "${_ve_code} OK     ${DIM}(${_ve_ms})${RESET}"
  else
    print_fail "$_ve_label" "HTTP ${_ve_code:-timeout}"
  fi
}

verify_endpoint "Gateway API" "http://localhost:3300/health"
verify_endpoint "Web UI"      "http://localhost:3200"

# Postgres check via docker compose exec
_pg_start=$(date +%s%N 2>/dev/null || date +%s)
if docker compose -f "$COMPOSE_FILE" exec -T postgres pg_isready -U postgres >/dev/null 2>&1; then
  _pg_end=$(date +%s%N 2>/dev/null || date +%s)
  if echo "$_pg_start" | grep -q "N$"; then
    _pg_ms="—"
  else
    _pg_ms=$(( (_pg_end - _pg_start) / 1000000 ))
    _pg_ms="${_pg_ms}ms"
  fi
  print_check "PostgreSQL" "connected  ${DIM}(${_pg_ms})${RESET}"
else
  print_fail "PostgreSQL" "not responding"
fi

# ── Done ──────────────────────────────────────────────────────────────────────

printf "\n\n  ${GREEN}${BOLD}✓  SignalPilot is running${RESET}\n\n\n"

printf "  %-18s%s\n" "Web UI"       "http://localhost:3200"
printf "  %-18s%s\n" "Gateway API"  "http://localhost:3300"
printf "  %-18s%s\n" "PostgreSQL"   "localhost:5600"

printf "\n\n  ${BOLD}Next steps${RESET}\n\n"
printf "    1. Open ${BOLD}http://localhost:3200${RESET} in your browser\n"
printf "    2. Connect a database:  ${DIM}sp connect mydb postgresql://...${RESET}\n"
printf "    3. Read the docs:       ${DIM}https://github.com/SignalPilot-Labs/SignalPilot${RESET}\n"
printf "\n\n"
