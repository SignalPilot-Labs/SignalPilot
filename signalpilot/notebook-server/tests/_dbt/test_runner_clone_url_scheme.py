"""``clone_git_repo`` must reject non-http(s) git URLs before spawning git.

The scheme guard is duplicated in two places -- the ``/api/dbt/clone_project``
handler and ``signalpilot._dbt.runner.clone_git_repo`` -- because the runner
has other in-process callers that never pass through the HTTP layer. The HTTP
half is covered in
``tests/_server/api/endpoints/test_dbt_agent_auth_e2e.py``; this module covers
the function directly, and asserts that no subprocess is spawned rather than
merely that an error is returned.

Why it matters (audit R2-1): git's ``ext::`` transport executes an arbitrary
shell command (``git clone 'ext::sh -c whoami'``), ``file://`` clones local
paths (exfiltration), and ``ssh://`` / scp-style URLs reach internal hosts.

Runs anywhere the server package imports -- no server, no network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

runner = pytest.importorskip("signalpilot._dbt.runner")

from signalpilot._server.files.path_confinement import (  # noqa: E402
    WORKSPACE_ROOT_ENV,
)

MALICIOUS_GIT_URLS = [
    "ext::sh -c whoami",
    "ext::sh -c 'touch /tmp/pwned'",
    "ext::bash -c id",
    "file:///etc/passwd",
    "file://C:/Windows/win.ini",
    "ssh://git@example.com/owner/repo.git",
    "git://example.com/owner/repo.git",
    "git@example.com:owner/repo.git",  # scp-style
    "/etc/passwd",  # bare local path
    "  ext::sh -c whoami  ",  # whitespace padding
    "EXT::sh -c whoami",  # case variation
    "HTTPX://example.com/repo.git",  # http-prefixed but not a real scheme
]


@pytest.fixture()
def no_subprocess(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Make any subprocess spawn a hard test failure, and record attempts."""
    calls: list[object] = []

    def _explode(*args: object, **kwargs: object) -> None:
        calls.append(args[0] if args else kwargs.get("args"))
        raise AssertionError(
            f"subprocess.run was called -- git was spawned: {args!r}"
        )

    monkeypatch.setattr(runner.subprocess, "run", _explode)
    return calls


@pytest.mark.parametrize("git_url", MALICIOUS_GIT_URLS)
def test_clone_git_repo_rejects_non_http_scheme(
    git_url: str, no_subprocess: list[object]
) -> None:
    success, path, error = runner.clone_git_repo(git_url, target_dir="/tmp/nope")

    assert success is False
    assert path == ""
    assert "Only http(s) git URLs are supported" in error
    assert no_subprocess == [], f"git was spawned for {git_url!r}"


@pytest.mark.parametrize(
    "git_url",
    [
        "https://github.com/owner/repo.git",
        "http://internal.example/owner/repo.git",
        "HTTPS://github.com/owner/repo.git",
        "  https://github.com/owner/repo.git  ",
    ],
)
def test_clone_git_repo_allows_http_schemes(
    git_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """http(s) URLs must reach git -- the guard must not break the feature."""
    spawned: list[list[str]] = []

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(cmd: list[str], **kwargs: object) -> _Result:
        spawned.append(cmd)
        return _Result()

    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/git")
    monkeypatch.setattr(runner.subprocess, "run", _fake_run)
    # target_dir is workspace-confined, so it has to live under the root.
    monkeypatch.setenv(WORKSPACE_ROOT_ENV, str(tmp_path))
    target_dir = str(tmp_path / "ok")

    success, path, error = runner.clone_git_repo(git_url, target_dir=target_dir)

    assert success is True, error
    assert Path(path) == Path(target_dir).resolve()
    assert len(spawned) == 1
    assert spawned[0][:2] == ["/usr/bin/git", "clone"]
    # The URL git receives is the one we passed, untouched.
    assert git_url in spawned[0]
