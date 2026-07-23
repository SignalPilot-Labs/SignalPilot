"""Schema-watch runner: introspect due connections, diff vs the stored
snapshot, and open a GitHub PR documenting any drift.

Each drift produces a PR from a deterministic branch
`schema-watch/<conn>-<new fingerprint[:12]>` adding
`schema-watch/<connection>/<UTC date>-<fp>.md` — a durable, reviewable audit
trail next to the dbt code that depends on the warehouse. Deterministic
branch naming makes retries collide (and get skipped) instead of duplicating
PRs when a run dies between PR creation and the DB commit.

Concurrency: a per-watch asyncio lock plus an early claim commit of
last_run_at keep the 60s loop, the run-now endpoint, and slow introspections
from double-running a watch. Watches run with per-watch sessions, bounded
parallelism, and a per-watch deadline so one hung warehouse can't stall the
rest.
"""

from __future__ import annotations

import asyncio
import base64
import datetime as dt
import logging
import time
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.connectors.schema_cache import _compute_schema_diff, _schema_fingerprint
from gateway.db.models import GatewaySchemaWatch

logger = logging.getLogger(__name__)

_WATCH_DEADLINE_S = 600
_WATCH_PARALLELISM = 3
_watch_locks: dict[str, asyncio.Lock] = {}


def _lock_for(watch_id: str) -> asyncio.Lock:
    return _watch_locks.setdefault(watch_id, asyncio.Lock())


def strip_schema(schema: dict) -> dict:
    """Reduce a connector snapshot to the structural fields fingerprint/diff
    consume. Volatile fields (row counts, sizes, stats) would otherwise make
    the stored JSON blob churn on every run despite an identical fingerprint."""
    out: dict = {}
    for key, t in schema.items():
        out[key] = {
            "schema": t.get("schema"),
            "name": t.get("name"),
            "type": t.get("type"),
            "columns": [
                {
                    "name": c.get("name"),
                    "type": c.get("type"),
                    "nullable": c.get("nullable"),
                    "primary_key": c.get("primary_key"),
                }
                for c in t.get("columns", [])
            ],
            "foreign_keys": t.get("foreign_keys", []),
        }
    return out


def render_diff_markdown(
    *, connection_name: str, diff: dict, old_fp: str | None, new_fp: str, table_count: int
) -> str:
    when = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# Schema change — `{connection_name}`",
        "",
        f"Detected {when} by SignalPilot schema watch.",
        f"Fingerprint `{(old_fp or 'none')[:12]}` → `{new_fp[:12]}` · {table_count} tables now visible.",
        "",
    ]
    added = diff.get("added_tables", [])
    removed = diff.get("removed_tables", [])
    modified = diff.get("modified_tables", [])
    if added:
        lines += ["## Added tables", *[f"- `{t}`" for t in added], ""]
    if removed:
        lines += ["## Removed tables ⚠️", *[f"- `{t}`" for t in removed], ""]
    if modified:
        lines.append("## Modified tables")
        for m in modified:
            lines.append(f"### `{m.get('table', m.get('name', '?'))}`")
            for c in m.get("added_columns", []):
                lines.append(f"- ➕ column `{c}`")
            for c in m.get("removed_columns", []):
                lines.append(f"- ➖ column `{c}` ⚠️")
            for tc in m.get("type_changes", []):
                lines.append(f"- 🔀 `{tc['column']}`: `{tc['old_type']}` → `{tc['new_type']}` ⚠️")
            lines.append("")
    if not (added or removed or modified):
        lines.append(
            "_Fingerprint changed with no table/column/type difference — "
            "likely nullability, primary-key, or foreign-key drift._"
        )
    lines += [
        "",
        "---",
        "⚠️ = potentially breaking for downstream models. Review dbt sources and",
        "staging models that reference these tables before the next build.",
    ]
    return "\n".join(lines)


def diff_is_empty(diff: dict) -> bool:
    return not (
        diff.get("added_tables") or diff.get("removed_tables") or diff.get("modified_tables")
    )


def _pr_title(connection_name: str, diff: dict) -> str:
    n_add = len(diff.get("added_tables", []))
    n_rem = len(diff.get("removed_tables", []))
    n_mod = len(diff.get("modified_tables", []))
    parts = []
    if n_add:
        parts.append(f"+{n_add} table{'s' if n_add != 1 else ''}")
    if n_rem:
        parts.append(f"-{n_rem} table{'s' if n_rem != 1 else ''}")
    if n_mod:
        parts.append(f"{n_mod} modified")
    summary = ", ".join(parts) or "drift detected"
    return f"Schema watch: {connection_name} — {summary}"


async def _resolve_watch_token(session: AsyncSession, watch: GatewaySchemaWatch) -> str | None:
    """Org-scoped token resolution.

    Unlike the webhook path (org derived FROM the link), a watch names an
    arbitrary repo — resolving cross-org would let org A open PRs on org B's
    linked repo with org B's installation token. Only this org's active link
    is considered; the shared PAT fallback applies in local mode only.
    """
    from gateway.config.github_bot import get_github_bot_settings
    from gateway.db.models import GatewayGitHubInstallation, GatewayGitHubRepoLink
    from gateway.runtime.mode import is_cloud_mode
    from gateway.store.github import get_valid_token

    link_result = await session.execute(
        select(GatewayGitHubRepoLink)
        .where(
            GatewayGitHubRepoLink.repo_full_name == watch.github_repo,
            GatewayGitHubRepoLink.status == "active",
            GatewayGitHubRepoLink.org_id == watch.org_id,
        )
        .order_by(GatewayGitHubRepoLink.created_at)
    )
    link = link_result.scalars().first()
    if link is not None:
        inst_result = await session.execute(
            select(GatewayGitHubInstallation).where(
                GatewayGitHubInstallation.id == link.installation_id,
                GatewayGitHubInstallation.status == "active",
            )
        )
        inst = inst_result.scalars().first()
        if inst is not None:
            try:
                return await get_valid_token(session, inst)
            except Exception as exc:
                logger.warning("Installation token failed for %s: %r", watch.github_repo, exc)
    if is_cloud_mode():
        return None
    return get_github_bot_settings().token or None


async def open_schema_diff_pr(
    client,
    *,
    repo: str,
    base_branch: str | None,
    connection_name: str,
    markdown: str,
    diff: dict,
    new_fp: str,
) -> str:
    """Create branch + diff file + PR. Returns the PR html_url.

    Branch name is deterministic per (connection, new fingerprint): a retry
    after a partial failure hits 'reference already exists' and is treated as
    already-reported rather than opening a duplicate.
    """
    import httpx

    base = base_branch or await client.get_default_branch(repo)
    base_sha = await client.get_ref_sha(repo, base)
    now = dt.datetime.now(dt.timezone.utc)
    branch = f"schema-watch/{connection_name}-{new_fp[:12]}"
    try:
        await client.create_branch(repo, branch, base_sha)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 422:
            logger.info("Schema-watch branch %s already exists — drift already reported", branch)
            return ""
        raise
    path = f"schema-watch/{connection_name}/{now.strftime('%Y-%m-%d')}-{new_fp[:12]}.md"
    await client.put_file(
        repo,
        path,
        content_b64=base64.b64encode(markdown.encode()).decode(),
        message=f"schema watch: {connection_name} drift {now.strftime('%Y-%m-%d')}",
        branch=branch,
    )
    n_add = len(diff.get("added_tables", []))
    n_rem = len(diff.get("removed_tables", []))
    n_mod = len(diff.get("modified_tables", []))
    body = (
        f"Automated schema-drift report for connection `{connection_name}`: "
        f"{n_add} added / {n_rem} removed / {n_mod} modified table(s).\n\n"
        f"Full report: `{path}` (in this PR's diff).\n\n"
        f"{markdown[:6000]}"
    )
    pr = await client.create_pull_request(
        repo,
        title=_pr_title(connection_name, diff),
        head=branch,
        base=base,
        body=body,
    )
    return pr.get("html_url", "")


async def run_watch(session: AsyncSession, watch: GatewaySchemaWatch) -> dict:
    """Run one watch: introspect, diff, PR on change. Updates the row.

    Skips (returns {"skipped": "already running"}) when another run of the
    same watch holds the lock.
    """
    from gateway.connectors.pool_manager import pool_manager
    from gateway.connectors.schema_cache import schema_cache
    from gateway.github_bot.client import GitHubBotClient
    from gateway.governance.context import current_org_id_var
    from gateway.store import Store

    lock = _lock_for(watch.id)
    if lock.locked():
        return {"connection": watch.connection_name, "skipped": "already running"}

    async with lock:
        now = time.time()
        result: dict = {"connection": watch.connection_name, "changed": False, "pr_url": None}
        token_ctx = current_org_id_var.set(watch.org_id)
        try:
            # Claim first: commit last_run_at before the (slow) introspection so
            # loop ticks and replicas don't double-run, and the gateway-DB
            # transaction isn't held open across warehouse/GitHub calls.
            watch.last_run_at = now
            watch.updated_at = now
            await session.commit()

            store = Store(session, org_id=watch.org_id)
            conn_info = await store.get_connection(watch.connection_name)
            if conn_info is None:
                raise RuntimeError(f"connection '{watch.connection_name}' not found")
            conn_str = await store.get_connection_string(watch.connection_name)
            extras = await store.get_credential_extras(watch.connection_name)
            await session.commit()  # close the read transaction before introspecting

            async with pool_manager.connection(
                conn_info.db_type, conn_str, credential_extras=extras, connection_name=watch.connection_name
            ) as connector:
                schema = await connector.get_schema()
            # Share the fresh snapshot with the org-scoped cache (MCP tools etc.)
            try:
                schema_cache.put(watch.connection_name, schema, track_diff=False)
            except Exception:
                pass

            fingerprint = _schema_fingerprint(schema)
            if watch.last_fingerprint is None:
                result["baselined"] = True
            elif fingerprint != watch.last_fingerprint:
                diff = _compute_schema_diff(watch.last_schema or {}, schema)
                result["diff"] = diff
                if diff_is_empty(diff):
                    # Nullability/PK/FK-only drift: advance the baseline
                    # silently rather than opening a content-free PR.
                    result["changed"] = True
                    result["suppressed"] = "no table-level differences"
                else:
                    markdown = render_diff_markdown(
                        connection_name=watch.connection_name,
                        diff=diff,
                        old_fp=watch.last_fingerprint,
                        new_fp=fingerprint,
                        table_count=len(schema),
                    )
                    gh_token = await _resolve_watch_token(session, watch)
                    if not gh_token:
                        raise RuntimeError(
                            f"no GitHub token for {watch.github_repo} (link the repo to this org "
                            "or set SP_GITHUB_BOT_TOKEN in local mode)"
                        )
                    client = GitHubBotClient(gh_token)
                    try:
                        pr_url = await open_schema_diff_pr(
                            client,
                            repo=watch.github_repo,
                            base_branch=watch.github_base_branch,
                            connection_name=watch.connection_name,
                            markdown=markdown,
                            diff=diff,
                            new_fp=fingerprint,
                        )
                    finally:
                        await client.aclose()
                    watch.last_change_at = now
                    watch.last_pr_url = pr_url or watch.last_pr_url
                    result.update(changed=True, pr_url=pr_url)
                    logger.info("Schema watch '%s': drift detected, PR %s", watch.connection_name, pr_url)

            if fingerprint != watch.last_fingerprint:
                watch.last_fingerprint = fingerprint
                watch.last_schema = strip_schema(schema)
            watch.last_error = None
            watch.updated_at = time.time()
            await session.commit()
            return result
        except Exception as exc:
            # Reset any failed transaction BEFORE mutating, or the error write
            # itself is discarded by the rollback.
            try:
                await session.rollback()
            except Exception:
                pass
            watch.last_run_at = now
            watch.last_error = str(exc)[:2000]
            watch.updated_at = time.time()
            try:
                await session.commit()
            except Exception:
                await session.rollback()
            logger.warning("Schema watch '%s' failed: %r", watch.connection_name, exc)
            result["error"] = str(exc)
            return result
        finally:
            current_org_id_var.reset(token_ctx)


async def run_due_watches(session_factory) -> int:
    """Run all enabled watches whose interval has elapsed. Returns count run.

    Each due watch gets its own session, a deadline, and bounded parallelism
    so one hung warehouse cannot stall other orgs' watches. The due check
    reads only scalar columns — last_schema blobs load per due watch only.
    """
    now = time.time()
    async with session_factory() as session:
        result = await session.execute(
            select(
                GatewaySchemaWatch.id,
                GatewaySchemaWatch.last_run_at,
                GatewaySchemaWatch.interval_s,
            ).where(GatewaySchemaWatch.enabled.is_(True))
        )
        due_ids = [
            row.id
            for row in result.fetchall()
            if not row.last_run_at or now - row.last_run_at >= row.interval_s
        ]

    if not due_ids:
        return 0

    sem = asyncio.Semaphore(_WATCH_PARALLELISM)

    async def _run_one(watch_id: str):
        async with sem:
            async with session_factory() as watch_session:
                watch = await watch_session.get(GatewaySchemaWatch, watch_id)
                if watch is None or not watch.enabled:
                    return
                try:
                    await asyncio.wait_for(run_watch(watch_session, watch), timeout=_WATCH_DEADLINE_S)
                except TimeoutError:
                    logger.warning("Schema watch '%s' exceeded %ds deadline", watch.connection_name, _WATCH_DEADLINE_S)

    await asyncio.gather(*[_run_one(w) for w in due_ids])
    return len(due_ids)


def new_watch(
    *,
    org_id: str,
    connection_name: str,
    github_repo: str,
    interval_s: int = 86400,
    github_base_branch: str | None = None,
    enabled: bool = True,
) -> GatewaySchemaWatch:
    now = time.time()
    return GatewaySchemaWatch(
        id=str(uuid.uuid4()),
        org_id=org_id,
        connection_name=connection_name,
        enabled=enabled,
        interval_s=max(60, interval_s),
        github_repo=github_repo,
        github_base_branch=github_base_branch,
        created_at=now,
        updated_at=now,
    )
