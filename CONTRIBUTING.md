# Contributing to SignalPilot

First off — thank you for taking the time to contribute. 🎉 SignalPilot is an open-source, governed gateway for AI agents accessing data stacks, and it gets better with every issue, idea, and pull request from the community.

This document explains how to propose changes, set up your environment, and get your work merged.

- [Code of Conduct](#code-of-conduct)
- [Ways to Contribute](#ways-to-contribute)
- [Before You Start](#before-you-start)
- [Development Setup](#development-setup)
- [Project Structure](#project-structure)
- [Making Changes](#making-changes)
- [Commit & Pull Request Guidelines](#commit--pull-request-guidelines)
- [Coding Standards](#coding-standards)
- [Adding a Database Connector](#adding-a-database-connector)
- [Reporting Bugs](#reporting-bugs)
- [Requesting Features](#requesting-features)
- [Security Issues](#security-issues)
- [License](#license)

---

## Code of Conduct

This project and everyone participating in it is governed by a simple principle: **be respectful, be constructive, and assume good intent.** Harassment, discrimination, or abusive behavior of any kind will not be tolerated. Report unacceptable behavior to **conduct@signalpilot.ai**.

---

## Ways to Contribute

You don't need to write code to help:

- 🐛 **Report bugs** — [open an issue](https://github.com/SignalPilot-Labs/signalpilot/issues) with clear reproduction steps
- 💡 **Suggest features** — start a [Discussion](https://github.com/SignalPilot-Labs/signalpilot/discussions) or open a feature-request issue
- 📖 **Improve docs** — fix typos, clarify setup steps, add examples
- 🔌 **Add a connector** — see [Adding a Database Connector](#adding-a-database-connector)
- 🧪 **Write tests** — coverage for connectors, governance rules, or MCP tools
- 🗣️ **Answer questions** — help others in [Discussions](https://github.com/SignalPilot-Labs/signalpilot/discussions)

---

## Before You Start

- **Search first.** Check [existing issues](https://github.com/SignalPilot-Labs/signalpilot/issues) and [pull requests](https://github.com/SignalPilot-Labs/signalpilot/pulls) to avoid duplicating work.
- **Open an issue for anything non-trivial.** For bug fixes and small changes, a PR is fine. For new features, connectors, or anything that changes public behavior, open an issue first so we can align on the approach before you invest time.
- **One logical change per PR.** Smaller PRs get reviewed and merged faster.

---

## Development Setup

### Prerequisites

- [Docker](https://www.docker.com/) & Docker Compose
- [Python 3.12+](https://www.python.org/) (gateway)
- [Node.js 22+](https://nodejs.org/) & [pnpm 10+](https://pnpm.io/) (web UI)
- Git

### Fork & clone

```bash
# Fork the repo on GitHub first, then:
git clone https://github.com/<your-username>/signalpilot.git
cd signalpilot
git remote add upstream https://github.com/SignalPilot-Labs/signalpilot.git
```

### Run the hot-reload development stack

Use the dev overlay for day-to-day work. It keeps the app isolated in Docker,
but bind-mounts the source tree and runs reload-capable commands so code edits
do not require image rebuilds.

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

If another local stack is already using a default port, override only the host
port and keep the in-container network unchanged:

```bash
SP_GATEWAY_PORT=3310 docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Put durable local overrides in the root `.env` file:

```bash
cp .env.example .env
```

Do not use `signalpilot/web/.env.local` for Docker port wiring. The dev compose
file sets the web container environment directly and clears `.next/dev` on boot
so a stale Next.js dev bundle cannot keep an old gateway URL.

After the first build, normal source edits should only need:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

| Service | Port | Development behavior |
|---------|------|----------------------|
| Web UI (Next.js) | 3200 | `next dev` with source bind-mounted, `.next` and `node_modules` in Docker volumes |
| Gateway (FastAPI + MCP) | 3300 | source bind-mounted; Uvicorn auto-restarts on Python edits using polling |
| Notebook server | 2718 | source bind-mounted; server auto-restarts on Python edits using polling |
| PostgreSQL | 5601 | persisted Docker volume |

The hot-reload overlay covers the main local product path: web, gateway,
notebook server, sandbox, and Postgres. It does not run the K8s pod-orchestration
mode, benchmark harnesses, plugin test images, or older workspaces/Notion-worker
services.

Rebuild only when dependencies, lockfiles, Dockerfiles, or system packages
change.

Useful checks:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml ps
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs -f gateway web
docker compose -f docker-compose.yml -f docker-compose.dev.yml down --remove-orphans
```

If Next.js exits after an interrupted build with a Turbopack cache error, restart
the web service; the dev overlay clears the corrupt cache path before `next dev`
starts.

### Optional local credentials

The core Docker stack runs without external credentials. You can open the web
app, use the gateway, start notebooks, and use local Postgres/Sandbox without
Claude, Slack, or Notion keys.

Add optional integration credentials to the root `.env` file. Existing machines
that already use `.slack.local.env` still work, but `.env` is the preferred file
for new local setups.

| Integration | Required only for | Local variables |
|-------------|-------------------|-----------------|
| Claude / Anthropic | notebook AI chat, AI delivery rendering, Slack/Notion analysis agents | `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN`; alternatively set `CLAUDE_HOST_CONFIG_DIR` to a host directory containing Claude Code credentials |
| Slack OAuth / Events | installing Slack, receiving Slack events, Slack progress/delivery | `SLACK_OAUTH_CLIENT_ID`, `SLACK_OAUTH_CLIENT_SECRET`, `SLACK_OAUTH_REDIRECT_URI`, `SLACK_SIGNING_SECRET`; Socket Mode additionally uses `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` |
| Notion OAuth / webhooks | installing Notion, receiving Notion comments, Notion delivery | `NOTION_OAUTH_CLIENT_ID`, `NOTION_OAUTH_CLIENT_SECRET`, `NOTION_OAUTH_REDIRECT_URI`, `NOTION_WEBHOOK_VERIFICATION_TOKEN` |

Slack and Notion callback/webhook URLs must be reachable by those providers. For
local development, point the redirect/webhook variables at a tunnel such as
ngrok or cloudflared that forwards to the gateway on `SP_GATEWAY_PORT`.

### Run the production-like local stack

Use the base compose file when you want to test the standalone image path rather
than the hot-reload workflow.

```bash
docker compose up --build
```

| Service | Port | Description |
|---------|------|-------------|
| Web UI (Next.js) | 3200 | Dashboard |
| Gateway (FastAPI + MCP) | 3300 | Governed queries, schema, dbt tools |
| PostgreSQL | 5601 | Persistence |

Default local credentials: `signalpilot` / `changeme_dev_only` / database `signalpilot`.

Connect the MCP server to Claude Code:

```bash
claude mcp add --transport http signalpilot http://localhost:3300/mcp
```

### Rebuilding a single service

```bash
# Only needed after dependency, lockfile, or Dockerfile changes
docker compose build gateway && docker compose up -d gateway

docker compose build web && docker compose up -d web
```

---

## Project Structure

```
signalpilot/
├── signalpilot/
│   ├── gateway/      # FastAPI backend — MCP server, REST API, governance
│   │   └── gateway/
│   │       ├── api/          # REST endpoints
│   │       ├── connectors/   # Database connectors + SSH tunneling
│   │       ├── governance/   # Budget, PII redaction, audit
│   │       ├── mcp/          # MCP tool definitions
│   │       ├── engine/       # SQL validation, LIMIT injection, denylist
│   │       └── db/           # SQLAlchemy ORM + async engine
│   └── web/          # Next.js 16 frontend
├── plugin/           # Claude Code plugin (skills + verifier agent)
├── sp-sandbox/       # gVisor sandboxed execution
├── benchmark/        # Spider 2.0-DBT + ADE-bench harnesses
└── docker-compose.yml
```

---

## Making Changes

1. **Sync with upstream** before branching:

   ```bash
   git checkout main
   git pull upstream main
   ```

2. **Create a descriptive branch:**

   ```bash
   git checkout -b fix/limit-injection-edge-case
   # or: feat/clickhouse-connector, docs/setup-clarification
   ```

3. **Make your change.** Keep it focused and add tests where it makes sense.

4. **Run the checks** (see [Coding Standards](#coding-standards)).

5. **Push and open a PR** against `main`.

---

## Commit & Pull Request Guidelines

### Commit messages

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<optional scope>): <short summary>
```

Common types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `ci`.

Examples:

```
feat(connectors): add ClickHouse connector
fix(engine): handle nested CTEs in LIMIT injection
docs: clarify MCP setup for Cursor
```

### Pull requests

A good PR:

- **Has a clear title and description** — what changed and why
- **Links the related issue** — `Closes #123`
- **Stays focused** — one logical change
- **Includes tests** for new behavior or bug fixes
- **Passes CI** — all checks green before review
- **Updates docs** if behavior or setup changed

We use **"Squash and merge"**, so your PR becomes a single commit on `main`. Don't worry about squashing your own commits beforehand.

Maintainers aim to give an initial response within a few business days. Please be patient and responsive to review feedback.

---

## Coding Standards

### Gateway (Python)

- Target **Python 3.12+**, fully type-hinted
- Format with **Ruff**; keep imports tidy
- Async-first — use `async`/`await` for I/O
- Add tests under `tests/` for new logic

```bash
cd signalpilot/gateway
ruff check .
ruff format .
pytest
```

### Web (TypeScript / Next.js)

- **TypeScript strict**, no `any` unless unavoidable
- Match existing component patterns and Tailwind conventions

```bash
cd signalpilot/web
pnpm install
pnpm lint
pnpm run build
```

> Match the style of the surrounding code. When in doubt, look at how similar code in the same module is written and follow that.

---

## Adding a Database Connector

Connectors live in `signalpilot/gateway/gateway/connectors/`. To add one:

1. Implement the connector interface (use an existing connector like the Postgres or DuckDB one as a reference).
2. Register it so it is discoverable by the connector registry.
3. Ensure governance still applies — **LIMIT injection, DDL/DML blocking, and the dangerous-function denylist must work for your dialect.**
4. Add tests covering connection, schema discovery, and a governed query.
5. Update the supported-databases list in the README.

Open an issue before starting a connector so we can confirm the dialect's governance requirements with you.

---

## Reporting Bugs

Open an [issue](https://github.com/SignalPilot-Labs/signalpilot/issues/new) and include:

- **What happened** vs. **what you expected**
- **Steps to reproduce** (minimal, exact)
- **Environment** — OS, Docker version, deployment mode (local/cloud), commit SHA
- **Logs** — relevant gateway/web output (redact any secrets)

---

## Requesting Features

Open a [Discussion](https://github.com/SignalPilot-Labs/signalpilot/discussions) or a feature-request issue describing:

- The problem you're trying to solve (not just the proposed solution)
- Who benefits and how
- Any alternatives you've considered

---

## Security Issues

**Do not open public issues for security vulnerabilities.** Follow the responsible-disclosure process in [SECURITY.md](SECURITY.md) — email **security@signalpilot.ai**.

---

## License

By contributing to SignalPilot, you agree that your contributions will be licensed under the [Apache License 2.0](LICENSE), the same license that covers this project.
