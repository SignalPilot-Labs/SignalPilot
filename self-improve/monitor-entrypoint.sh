#!/bin/bash
set -e

# Ensure shared data volume is writable by all containers (agent runs as non-root)
chmod -R a+rw /data 2>/dev/null || true

# Start FastAPI backend on port 3401
uvicorn monitor.app:app --host 0.0.0.0 --port 3401 &
FASTAPI_PID=$!

# Wait for FastAPI to be ready
for i in $(seq 1 30); do
    if curl -sf http://localhost:3401/api/runs > /dev/null 2>&1; then
        echo "[monitor] FastAPI backend ready on :3401"
        break
    fi
    sleep 0.5
done

# Start Next.js frontend on port 3402 (behind nginx)
cd /app/monitor-web
API_URL=http://localhost:3401 npx next start --port 3402 &
NEXT_PID=$!

echo "[monitor] Next.js frontend ready on :3402"

# Start nginx reverse proxy on port 3400
# Routes /api/* → FastAPI :3401 (unbuffered, SSE-friendly)
# Routes /*    → Next.js :3402
nginx &
NGINX_PID=$!

echo "[monitor] nginx proxy ready on :3400"

# Wait for any process to exit
wait -n $FASTAPI_PID $NEXT_PID $NGINX_PID
