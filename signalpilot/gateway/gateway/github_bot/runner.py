"""PR-scan orchestration: token → PR fetch → verify → comment + status.

Kept out of the API layer (mirrors schema_watch/runner.py). Concurrency
policy: one in-flight scan per (repo, pr) — a newer push supersedes the
running scan for the same PR (cancel-and-replace) so an older slow scan can
never overwrite newer results; a global semaphore caps total warehouse load.
"""

from __future__ import annotations

import asyncio
import logging

from gateway.config.github_bot import get_github_bot_settings

logger = logging.getLogger(__name__)

_SCAN_DEADLINE_S = 30 * 60
_scan_semaphore = asyncio.Semaphore(4)
_active_scans: dict[tuple[str, int], asyncio.Task] = {}


async def run_pr_scan(*, org_id: str, repo: str, pr_number: int, connection_name: str | None) -> dict:
    """Fetch PR files, verify changed models, comment + set status. Returns summary."""
    from gateway.db.engine import get_session_factory
    from gateway.github_bot.client import GitHubBotClient, resolve_bot_token
    from gateway.github_bot.scanner import render_report_markdown, scan_pr_models
    from gateway.store import Store

    token = await resolve_bot_token(repo)
    if not token:
        raise RuntimeError(f"no GitHub token available for {repo} (link the repo or set SP_GITHUB_BOT_TOKEN)")
    client = GitHubBotClient(token)

    try:
        pr = await client.get_pr(repo, pr_number)
        head_sha = pr["head"]["sha"]
        await client.set_commit_status(repo, head_sha, "pending", "verifying changed models…")

        cfg = get_github_bot_settings()
        conn = connection_name or cfg.default_connection
        try:
            files = await client.list_pr_files(repo, pr_number)
            # Session only wraps the scan's store lookups; warehouse queries run
            # inside scan_pr_models on the connector pool, not this session.
            factory = get_session_factory()
            async with factory() as session:
                store = Store(session, org_id=org_id, user_id=None)
                report = await asyncio.wait_for(
                    scan_pr_models(store, repo=repo, pr_number=pr_number, connection_name=conn, files=files),
                    timeout=_SCAN_DEADLINE_S,
                )
            body = render_report_markdown(report)
            await client.upsert_pr_comment(repo, pr_number, body)
            state = {"pass": "success", "warn": "success", "fail": "failure"}[report.verdict]
            n_fail = sum(1 for c in report.checks if c.verdict == "fail")
            desc = (
                f"{len(report.checks)} model(s) verified — "
                + (f"{n_fail} failing" if n_fail else ("warnings" if report.verdict == "warn" else "all passed"))
            )
            await client.set_commit_status(repo, head_sha, state, desc)
            logger.info("PR scan %s#%d verdict=%s models=%d", repo, pr_number, report.verdict, len(report.checks))
            return {
                "repo": repo,
                "pr_number": pr_number,
                "verdict": report.verdict,
                "models": [c.model for c in report.checks],
                "connection": conn,
            }
        except Exception as exc:
            logger.warning("PR scan failed %s#%d: %r", repo, pr_number, exc)
            try:
                # Exception text can leak URLs/hostnames — keep the status generic.
                await client.set_commit_status(repo, head_sha, "error", "scan error — see gateway logs")
            except Exception:
                pass
            raise
    finally:
        await client.aclose()


def schedule_scan(org_id: str, repo: str, pr_number: int) -> None:
    """Background scan keyed by (repo, pr): a newer event supersedes the old scan."""
    key = (repo, pr_number)
    old = _active_scans.get(key)
    if old and not old.done():
        old.cancel()
        logger.info("Superseding in-flight scan for %s#%d", repo, pr_number)

    async def _run():
        try:
            async with _scan_semaphore:
                await run_pr_scan(org_id=org_id, repo=repo, pr_number=pr_number, connection_name=None)
        except asyncio.CancelledError:
            logger.info("Scan for %s#%d cancelled (superseded)", repo, pr_number)
        except Exception:
            pass  # already logged in run_pr_scan
        finally:
            if _active_scans.get(key) is task:
                _active_scans.pop(key, None)

    task = asyncio.create_task(_run())
    _active_scans[key] = task
