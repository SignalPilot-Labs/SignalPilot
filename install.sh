#!/bin/sh
# SignalPilot Installer — thin bootstrap
# Delegates to the Python-based `sp install` command.
# https://github.com/SignalPilot-Labs/SignalPilot

set -e

# ─── ANSI ────────────────────────────────────────────────────────────────────

if [ "${SP_NO_COLOR:-}" = "1" ] || [ ! -t 1 ]; then
  BOLD="" DIM="" RESET=""
else
  BOLD="\033[1m" DIM="\033[2m" RESET="\033[0m"
fi

# ─── Help ────────────────────────────────────────────────────────────────────

for arg in "$@"; do
  case "$arg" in
    --help|-h)
      printf "\n  ${BOLD}SignalPilot Installer${RESET}\n\n"
      printf "  Usage:  ./install.sh [flags]\n\n"
      printf "  Flags:\n"
      printf "    --skip-build    Skip Docker build step\n"
      printf "    --dev           Use docker-compose.dev.yml\n"
      printf "    --no-color        Disable ANSI color codes\n"
      printf "    --non-interactive  Skip interactive prompts (for curl | sh)\n"
      printf "    --help            Show this help\n\n"
      exit 0
      ;;
    --no-color) export SP_NO_COLOR=1 ;;
    --non-interactive) NON_INTERACTIVE=1 ;;
  esac
done

# ─── Pipe detection ─────────────────────────────────────────────────────────

if [ ! -t 0 ]; then
  # stdin is a pipe (curl | sh) — enable non-interactive mode
  NON_INTERACTIVE="${NON_INTERACTIVE:-1}"
fi

# ─── Header ──────────────────────────────────────────────────────────────────

printf "\n"
printf "  ┌───────────────────────────────────────────┐\n"
printf "  │                                           │\n"
printf "  │     s i g n a l p i l o t                 │\n"
printf "  │                                           │\n"
printf "  │     Installer  v0.1.0                     │\n"
printf "  │     github.com/SignalPilot-Labs           │\n"
printf "  │                                           │\n"
printf "  └───────────────────────────────────────────┘\n"
printf "\n"

# ─── Detect repo ─────────────────────────────────────────────────────────────

SCRIPT_DIR=$(cd "$(dirname "$0")" 2>/dev/null && pwd || pwd)
CLONE_URL="https://github.com/SignalPilot-Labs/SignalPilot.git"
REPO_DIR=""

if [ -f "${SCRIPT_DIR}/signalpilot/gateway/pyproject.toml" ]; then
  REPO_DIR="$SCRIPT_DIR"
else
  REPO_DIR="${HOME}/.signalpilot"
  if [ ! -d "${REPO_DIR}/.git" ]; then
    printf "  ${DIM}Cloning SignalPilot...${RESET}\n"
    if ! git clone --depth 1 "$CLONE_URL" "$REPO_DIR" >/dev/null 2>&1; then
      printf "  ✗  Clone failed. Check network and repo access.\n\n"
      exit 1
    fi
    printf "  ✓  Cloned to %s\n\n" "$REPO_DIR"
  fi
fi

# ─── Check Python ────────────────────────────────────────────────────────────

check_python() {
  for cmd in python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
      _ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
      _major=$(echo "$_ver" | cut -d. -f1)
      _minor=$(echo "$_ver" | cut -d. -f2)
      if [ "$_major" -ge 3 ] && [ "$_minor" -ge 12 ] 2>/dev/null; then
        PYTHON_CMD="$cmd"
        PYTHON_VER="$_ver"
        return 0
      fi
    fi
  done
  return 1
}

if ! check_python; then
  printf "  ✗  Python 3.12+ is required but not found.\n\n"
  _kernel=$(uname -s)
  if [ "$_kernel" = "Darwin" ]; then
    printf "  Install via Homebrew:\n"
    printf "    ${BOLD}brew install python@3.12${RESET}\n\n"
  else
    printf "  Install from:\n"
    printf "    ${BOLD}https://www.python.org/downloads/${RESET}\n\n"
  fi
  exit 1
fi

printf "  ${DIM}Using %s (%s)${RESET}\n\n" "$PYTHON_CMD" "$PYTHON_VER"

# ─── Create venv and install ─────────────────────────────────────────────────

VENV_DIR=$(mktemp -d /tmp/sp-install-venv-XXXXXX)

cleanup() {
  rm -rf "$VENV_DIR" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

printf "  ${DIM}Preparing installer...${RESET}\n"
"$PYTHON_CMD" -m venv "$VENV_DIR" 2>/dev/null
if ! "${VENV_DIR}/bin/pip" install -q -e "${REPO_DIR}/signalpilot/gateway" 2>/dev/null; then
  printf "  ✗  Failed to install SignalPilot CLI.\n\n"
  exit 1
fi
printf "\033[1A\033[2K"

# ─── Delegate to sp install ──────────────────────────────────────────────────

if [ "${NON_INTERACTIVE:-}" = "1" ]; then
  exec "${VENV_DIR}/bin/sp" install --non-interactive "$@"
else
  exec "${VENV_DIR}/bin/sp" install "$@"
fi
