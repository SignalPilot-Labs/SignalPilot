---
description: "Use when working on the gateway module — adding auth, rate limiting, improving the SQL engine, fixing CORS, or hardening endpoints."
---

# Gateway Hardening Guide

## Architecture

The gateway (`/workspace/signalpilot/gateway/gateway/`) is a FastAPI app that:

- Receives SQL queries and code execution requests
- Validates SQL through the governance engine (`engine/__init__.py`)
- Routes queries to database connectors (`connectors/postgres.py`)
- Forwards code execution to the Firecracker sandbox (`sandbox_client.py`)
- Manages credentials in memory (`store.py`)
- Exposes MCP tools via `mcp_server.py`

## Key Files

| File                     | Purpose                    | Critical Issues                              |
| ------------------------ | -------------------------- | -------------------------------------------- |
| `main.py`                | FastAPI app, all endpoints | No auth on any endpoint                      |
| `engine/__init__.py`     | SQL validation             | sqlglot fallback bypasses all checks         |
| `connectors/postgres.py` | DB connector               | New pool per query                           |
| `store.py`               | Credential vault           | Plain dict, settings.json has plaintext keys |
| `sandbox_client.py`      | Firecracker client         | Optional auth never validated server-side    |
| `models.py`              | Pydantic models            | budget_usd exists but never enforced         |

## Auth Implementation Plan

1. Add API key middleware to `main.py`
2. Validate `api_key` from `models.py:GatewaySettings`
3. Require auth header on all `/api/*` endpoints
4. Exempt health check endpoints

## Rate Limiting

```python
from collections import defaultdict
import time

class RateLimiter:
    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self.counts: dict[str, list[float]] = defaultdict(list)
        self.max_requests = max_requests
        self.window = window_seconds

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        self.counts[key] = [t for t in self.counts[key] if now - t < self.window]
        if len(self.counts[key]) >= self.max_requests:
            return False
        self.counts[key].append(now)
        return True
```

## SQL Engine Improvements

- Make sqlglot a hard dependency, not optional
- Add parameterized query support
- Improve stacking detection (current regex bypassed with comments)
- Add query cost estimation
