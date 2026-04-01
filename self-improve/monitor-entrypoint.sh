#!/bin/bash
set -e

# Start FastAPI backend on port 3401 (exposed for SSE streaming)
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

# Start Next.js frontend on port 3400 (exposed to host)
# API calls are proxied to FastAPI via next.config.ts rewrites
cd /app/monitor-web
API_URL=http://localhost:3401 npx next start --port 3400 &
NEXT_PID=$!

echo "[monitor] Next.js frontend ready on :3400"

# Wait for either process to exit
wait -n $FASTAPI_PID $NEXT_PID
