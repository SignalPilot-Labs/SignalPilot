"""Live test: the agent-in-a-Vercel-sandbox git workflow, end to end.

Proves the workflow the chat/eval systems depend on: create a sandbox, clone a
repo into it at creation time (GitCheckout), create a working branch, produce
an artifact, commit it, and read the result back — with the sandbox destroyed
afterwards.

Costs real money (~$0.02/run) and needs network, so it runs only when
explicitly requested:

    SP_TEST_LIVE_VERCEL=1 VERCEL_TOKEN=... VERCEL_TEAM_ID=... VERCEL_PROJECT_ID=... \
        pytest tests/test_vercel_agent_workflow_live.py

Optional: SP_TEST_VERCEL_GIT_URL overrides the public repo used for the clone.
"""

from __future__ import annotations

import os
import time

import pytest

_REQUIRED = ("VERCEL_TOKEN", "VERCEL_TEAM_ID", "VERCEL_PROJECT_ID")
pytestmark = pytest.mark.skipif(
    os.environ.get("SP_TEST_LIVE_VERCEL") != "1" or any(not os.environ.get(v) for v in _REQUIRED),
    reason="live Vercel test: set SP_TEST_LIVE_VERCEL=1 and VERCEL_* credentials",
)

_CLONE_URL = os.environ.get("SP_TEST_VERCEL_GIT_URL", "https://github.com/dbt-labs/jaffle_shop.git")


@pytest.fixture
def runtime():
    from gateway.config.sandbox_runtime import get_sandbox_runtime_settings, reset_sandbox_runtime_settings
    from gateway.sandbox_runtime.vercel import VercelSandboxRuntime

    reset_sandbox_runtime_settings()
    settings = get_sandbox_runtime_settings()
    assert settings.enabled
    return VercelSandboxRuntime(project_id=settings.vercel_project_id)


async def test_agent_branch_and_artifact_commit_in_sandbox(runtime):
    from gateway.sandbox_runtime.base import GitCheckout, SandboxSpec

    started = time.monotonic()
    sandbox_id = await runtime.create(
        SandboxSpec(
            time_limit_seconds=600,
            git=GitCheckout(url=_CLONE_URL, depth=1),
            tags={"sp-test": "agent-workflow"},
        )
    )
    create_seconds = time.monotonic() - started
    try:
        # 1. Locate the checkout: GitSource clones into $HOME/<repo-name>
        # (observed /vercel/jaffle_shop on the v0.9 runtime); fall back to a
        # bounded find in case the provider moves it.
        repo_name = _CLONE_URL.rstrip("/").removesuffix(".git").rsplit("/", 1)[-1]
        find = await runtime.exec(
            sandbox_id,
            f'if [ -d "$HOME/{repo_name}/.git" ]; then echo "$HOME/{repo_name}"; '
            "else find / -maxdepth 4 -name .git -not -path '/proc/*' 2>/dev/null | head -1 | xargs -r dirname; fi",
            timeout_seconds=60,
        )
        repo_dir = find.stdout.strip().splitlines()[-1] if find.stdout.strip() else ""
        assert repo_dir, f"clone not found: {find.stdout[:300]} {find.stderr[:200]}"

        # 2. Agent branch + artifact + commit.
        work = await runtime.exec(
            sandbox_id,
            f"cd {repo_dir} && git checkout -b signalpilot-agent/live-test && "
            "mkdir -p artifacts && echo '{\"finding\": 42}' > artifacts/report.json && "
            "git -c user.email=agent@signalpilot.ai -c user.name=sp-agent add artifacts && "
            "git -c user.email=agent@signalpilot.ai -c user.name=sp-agent commit -m 'agent artifact' && "
            "git log --oneline -1 && git show --stat --oneline HEAD | tail -2",
            timeout_seconds=120,
        )
        assert work.returncode == 0, work.stderr[:500]
        assert "agent artifact" in work.stdout
        assert "report.json" in work.stdout

        # 3. The artifact is readable back out of the sandbox (write-back seam).
        content = await runtime.read_file(sandbox_id, f"{repo_dir}/artifacts/report.json")
        assert content is not None and b"42" in content

        # 4. Speed floor: sandbox+clone should be fast enough for interactive use.
        assert create_seconds < 60, f"sandbox+clone took {create_seconds:.1f}s"
    finally:
        await runtime.destroy(sandbox_id)
