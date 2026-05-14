# Vendored AutoFyn snapshot

Source: /opt/autofyn/ (not a git checkout; commit = unknown)
Date copied: 2026-05-01
Ownership: Common ownership with SignalPilot-Labs; copy authorized by repo owner in product brief. No separate LICENSE file in source; not blocking.

## Changes vs source

- Excluded handlers/repo.py — AutoFyn GitHub PR-creating handlers; Workspaces uses gateway/web for GitHub integration.
- Excluded db/ — AutoFyn run-history Postgres ORM; Workspaces will use its own schema in Round 2+.
- Excluded __pycache__/, .autofyn/, .claude/, .gitignore — private state.
- Excluded pyproject.toml — sandbox is non-installable in Round 1; packaging deferred to Round 2.
- server.py: removed handlers.repo import and route registration; removed db.connection import and startup pool init.
- handlers/__init__.py: removed repo re-export (if present).
- Dockerfile.gvisor: install path /opt/autofyn -> /opt/workspaces; skills COPY source = ./plugin/ (TODO round-7); removed db/ and handlers/repo.py COPY lines.

## To do in later rounds

- Round 2: add Workspaces-specific DB layer (schema: workspaces).
- Round 7: fix Dockerfile build context; populate plugin/ if empty.
