# SignalPilot — Local Development Setup

Run the gateway (FastAPI + MCP) and web app (Next.js) locally against a Dockerized Postgres.

---

## Prerequisites

- **Docker Desktop** — for running PostgreSQL
- **Python 3.12+** — for the gateway
- **Node.js 22+** and **npm** — for the web app

---

## 1. Start PostgreSQL

Use the existing `docker-compose.yml` and bring up just the database:

```bash
docker compose up -d db
```

This starts Postgres 17 on **port 5601** with:
- User: `signalpilot`
- Password: `changeme_dev_only`
- Database: `signalpilot`

Verify it's healthy:

```bash
docker compose ps db
```

The gateway auto-creates all tables on first startup — no manual migrations needed.

---

## 2. Start the Gateway

```bash
cd signalpilot/gateway
pip install -e .
```

The CLI auto-loads environment from `.env.local` (preferred) or `.env` in the current directory. A `.env.local` is already provided at `signalpilot/gateway/.env.local` with the right defaults.

```bash
cd signalpilot/gateway
python -m gateway.cli serve --reload
```

No manual env var exports needed — dotenv handles it.

> **Note:** Don't use `sp serve` — `sp` is aliased to `Set-ItemProperty` in PowerShell.
> `python -m gateway.cli serve` works on both Windows and Linux.

The gateway starts on **http://localhost:3300**. On first boot it creates all `gateway_*` tables in Postgres automatically.

### Gateway env reference

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | (required) | Postgres connection string with `asyncpg` driver |
| `SP_DEPLOYMENT_MODE` | `local` | `local` = no auth required, `cloud` = Clerk JWT |
| `SP_ALLOWED_ORIGINS` | `http://localhost:3000,http://localhost:3200` | CORS origins (comma-separated) |
| `SP_DATA_DIR` | `/data` | Directory for local API key file and data |
| `SP_ENCRYPTION_KEY` | (auto-generated) | Fernet key for credential encryption |
| `SP_SANDBOX_MANAGER_URL` | `http://localhost:8180` | Sandbox service URL (not needed for basic local dev) |

A `.env.local` file is provided at `signalpilot/gateway/.env.local` with these defaults.

---

## 3. Start the Web App

```bash
cd signalpilot/web
npm install
```

The `.env.local` at `signalpilot/web/.env.local` is already configured:

```
NEXT_PUBLIC_DEPLOYMENT_MODE=local
NEXT_PUBLIC_GATEWAY_URL=http://localhost:3300
```

Start the dev server:

```bash
npm run dev
```

The web app starts on **http://localhost:3200**.

### Local API key (optional)

In Docker, the gateway writes a local API key to a shared volume and the web app reads it automatically. When running both services locally outside Docker, the web app works without it — in `local` deployment mode, auth is optional.

If you need the key (e.g., for testing authenticated flows):

```bash
# Generate the key from the gateway
python -c "from gateway.store import get_local_api_key; print(get_local_api_key())"
```

Then set it in the web app's environment before starting:

```bash
# PowerShell
$env:SP_LOCAL_API_KEY = "<key from above>"
npm run dev

# Bash
SP_LOCAL_API_KEY="<key from above>" npm run dev
```

---

## 4. Connect MCP to Claude Code

Once the gateway is running:

```bash
claude mcp add --transport http signalpilot http://localhost:3300/mcp
```

---

## 5. Verify Everything Works

1. **Gateway health**: Open http://localhost:3300/docs — the FastAPI Swagger UI should load.
2. **Web UI**: Open http://localhost:3200 — the dashboard should load and connect to the gateway.
3. **MCP**: Run `claude mcp list` to confirm the signalpilot server is registered.

---

## Sandbox (not required)

The sandbox service (gVisor-based code execution) is **not needed** for local development. It's only used for sandboxed DuckDB/SQLite file connections and Python code execution, both of which are disabled in the current local workflow.

If you ever need it, use the full Docker Compose instead:

```bash
docker compose up --build
```

---

## Stopping Services

```bash
# Stop Postgres
docker compose down db

# Stop Postgres AND delete data
docker compose down -v db
```

---

## Troubleshooting

### Gateway: `DATABASE_URL is required but not set`

Make sure you exported the env var before running the gateway. Check with:

```bash
# PowerShell
$env:DATABASE_URL

# Bash
echo $DATABASE_URL
```

### Gateway: connection refused to Postgres

Postgres might still be starting. Wait for the health check:

```bash
docker compose ps db
```

The `STATUS` column should show `healthy`.

### Web: can't reach gateway (CORS or network error)

- Confirm the gateway is running on port 3300.
- Check `NEXT_PUBLIC_GATEWAY_URL` in `signalpilot/web/.env.local` is `http://localhost:3300`.
- Restart the Next.js dev server after changing `.env.local` — Next.js only reads env files at startup.

### Reset everything

```bash
docker compose down -v db
docker compose up -d db
# Restart gateway — tables are re-created on boot
```
