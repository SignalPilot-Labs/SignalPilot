#!/usr/bin/env bash
# SignalPilot local dev launcher
# Usage: ./dev.sh [up|down|build|restart]
#
# Auto-generates a shared local API key on first run.
# Both gateway and web containers use it for local auth.

set -euo pipefail
cd "$(dirname "$0")"

ENV_FILE=".env"
KEY_VAR="SP_LOCAL_API_KEY"

# Generate local API key if not already in .env
if ! grep -q "^${KEY_VAR}=" "$ENV_FILE" 2>/dev/null; then
  KEY="sp_local_$(openssl rand -hex 16)"
  echo "${KEY_VAR}=${KEY}" >> "$ENV_FILE"
  echo "[dev] Generated local API key: ${KEY:0:12}..."
fi

ACTION="${1:-up}"

case "$ACTION" in
  up)
    docker compose -f docker-compose.dev.yml up --build -d "$@"
    ;;
  down)
    docker compose -f docker-compose.dev.yml down "$@"
    ;;
  build)
    docker compose -f docker-compose.dev.yml build "$@"
    ;;
  restart)
    docker compose -f docker-compose.dev.yml down
    docker compose -f docker-compose.dev.yml up --build -d
    ;;
  logs)
    docker compose -f docker-compose.dev.yml logs -f "${@:2}"
    ;;
  *)
    docker compose -f docker-compose.dev.yml "$@"
    ;;
esac
