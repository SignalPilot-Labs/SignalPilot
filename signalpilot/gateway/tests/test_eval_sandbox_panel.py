"""Verify inventory, events, logs, and progress in the evaluation sandbox panel.

An organization cannot view another organization's sandboxes. Responses do not
contain credentials. Each live stream terminates. The tests use asynchronous
test doubles or SQLite for database-backed ownership checks.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from gateway.config.evals import EvalRunSettings
from gateway.evals import runner, sandboxes

from ._eval_sandbox_panel_support import (
    ANTHROPIC_KEY,
    MCP_KEY_B64,
    OAUTH_TOKEN,
    POD_A,
    POD_B,
    RUN_A,
    RUN_B,
    _client,
    _eval_secrets,
    _patch_owners,
    _postgres_dsn,
    _seed_run,
    db,
    sqlite_factory,
)


class TestSandboxNameValidation:
    @pytest.mark.parametrize(
        "name",
        [
            "sp-eval-aaaaaaaaaaaa",
            "a" * 12,
            "0123456789abcdef" * 4,
            # Vercel-generated sandbox names
            "gold-planned-chicken-DbtqQZ",
            "ivory-complicated-pelican-euE6FH",
        ],
    )
    def test_accepts_backend_minted_names(self, name: str) -> None:
        assert sandboxes.is_valid_sandbox_name(name)

    @pytest.mark.parametrize(
        "name",
        ["", "../../etc/passwd", "sp-eval-../x", "kube-apiserver", "sp-eval-AAAAAAAAAAAA", "sp-eval-aaaa aaaa"],
    )
    def test_refuses_anything_else(self, name: str) -> None:
        assert not sandboxes.is_valid_sandbox_name(name)

    def test_route_refuses_a_traversal_name(self) -> None:
        with _client("org-a") as client:
            assert client.get("/api/evals/sandboxes/..%2F..%2Fsecrets/events").status_code in (400, 404)


# Verify redaction.


class TestRedaction:
    def test_configured_tokens_are_stripped(self) -> None:
        out = sandboxes.redact(f"failed to pull using {OAUTH_TOKEN} and {ANTHROPIC_KEY}")
        assert OAUTH_TOKEN not in out
        assert ANTHROPIC_KEY not in out
        assert sandboxes.REDACTED in out

    def test_unknown_token_shapes_are_stripped(self) -> None:
        out = sandboxes.redact("env SP_MCP_JSON_B64=" + MCP_KEY_B64)
        assert MCP_KEY_B64 not in out

    def test_bearer_headers_are_stripped(self) -> None:
        assert "hunter2" not in sandboxes.redact("Authorization: hunter2hunter2hunter2")
        assert "abcd1234" not in sandboxes.redact("X-API-Key=abcd1234")

    @pytest.mark.parametrize(
        ("line", "secret"),
        [
            (
                "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature",
                "eyJhbGciOiJIUzI1NiJ9.payload.signature",
            ),
            ("Bearer ghs_16CharsOfGitHubInstallTokenAAAA", "ghs_16CharsOfGitHubInstallTokenAAAA"),
            (
                "Authorization=Bearer ghs_TOKENVALUE_NOT_REDACTED_HERE",
                "ghs_TOKENVALUE_NOT_REDACTED_HERE",
            ),
        ],
    )
    def test_bearer_token_value_is_stripped(self, line: str, secret: str) -> None:
        assert secret not in sandboxes.redact(line)

    def test_branch_password_environment_value_is_stripped(self) -> None:
        secret = "Xk3n-" + "_QzT9aVbC2dEfGhIjKlMnOpQrSt"
        assert secret not in sandboxes.redact(f"PGPASSWORD={secret}")

    def test_presigned_url_credentials_are_stripped(self) -> None:
        access_key = "minioadmin%2F20260803%2Fus-east-1%2Fs3%2Faws4_request"
        signature = "0123456789abcdef" * 4
        url = (
            "http://eval-object-proxy:9000/object?X-Amz-Algorithm=AWS4-HMAC-SHA256"
            f"&X-Amz-Credential={access_key}&X-Amz-Signature={signature}"
        )
        out = sandboxes.redact(url)
        assert access_key not in out
        assert signature not in out

    def test_image_digests_survive(self) -> None:
        """An ImagePullBackOff message is useless without the digest it failed on."""
        digest = "a" * 64
        assert digest in sandboxes.redact(f"Failed to pull image reg/eval@sha256:{digest}")

    def test_empty_input(self) -> None:
        assert sandboxes.redact("") == ""

    def test_exact_runtime_secret_is_removed(self) -> None:
        secret = _postgres_dsn("branch_role:password@warehouse/eval-task")
        out = sandboxes.redact(
            f"connecting with {secret}",
            extra_secrets=[secret],
        )
        assert secret not in out
        assert sandboxes.REDACTED in out

    def test_dsn_password_is_removed_when_logged_without_the_url(self) -> None:
        dsn = _postgres_dsn("branch_role:p%40ssword-012345@warehouse/eval-task")
        out = sandboxes.redact(
            "driver rejected password p@ssword-012345",
            extra_secrets=[dsn],
        )
        assert "p@ssword-012345" not in out
        assert sandboxes.REDACTED in out

    def test_eval_api_key_is_removed_when_logged_bare(self) -> None:
        key = "sp_" + "a1" * 16
        out = sandboxes.redact(f"decoded key: {key}")
        assert key not in out

    def test_stream_redaction_survives_chunk_boundaries(self) -> None:
        key = "sp_" + "a1" * 16
        buf = sandboxes._RedactionBuffer()
        assert buf.feed("decoded key: " + key[:12]) == ""
        assert buf.feed(key[12:] + "\n") == f"decoded key: {sandboxes.REDACTED}\n"
        assert buf.flush() == ""

    def test_stream_redacts_dsn_userinfo(self) -> None:
        out = sandboxes.redact(_postgres_dsn("branch_role:p%40ssword-012345@warehouse/eval-task"))
        assert "branch_role" not in out
        assert "p%40ssword-012345" not in out


# Verify inventory.


class TestInventory:
    def test_view_requires_an_org(self) -> None:
        with pytest.raises(ValueError, match="org_id"):
            sandboxes.DockerSandboxView(EvalRunSettings(), org_id="")
        with pytest.raises(ValueError, match="org_id"):
            sandboxes.VercelSandboxView(EvalRunSettings(), org_id="")


# Verify events.


class TestEvents:
    async def test_docker_says_events_are_unsupported_rather_than_faking_them(self) -> None:
        view = sandboxes.DockerSandboxView(EvalRunSettings(), org_id="org-a")
        try:
            body = await view.events("abcdefabcdef")
        finally:
            await view.aclose()
        assert body["supported"] is False
        assert body["events"] == []


# Verify cross-org isolation.


class TestCrossOrgIsolation:
    async def test_sandbox_index_is_per_org(self, db) -> None:
        await _seed_run(db, "org-a", RUN_A, pod=POD_A)
        await _seed_run(db, "org-b", RUN_B, pod=POD_B)
        assert POD_A in await runner.sandbox_index("org-a")
        assert POD_A not in await runner.sandbox_index("org-b")
        assert POD_B not in await runner.sandbox_index("org-a")

    async def test_a_foreign_pod_gets_no_attribution(self, db) -> None:
        """org-b's index must not name org-a's question, even by pod name."""
        await _seed_run(db, "org-a", RUN_A, pod=POD_A)
        assert await runner.sandbox_index("org-b") == {}

    async def test_run_exists_is_org_scoped(self, db) -> None:
        await _seed_run(db, "org-a", RUN_A, pod=POD_A)
        assert await runner.run_exists("org-a", RUN_A) is True
        assert await runner.run_exists("org-b", RUN_A) is False

    async def test_docker_ownership_requires_a_run_in_this_orgs_state(self, monkeypatch) -> None:
        async def fake_run_exists(org_id: str, run_id: str) -> bool:
            return org_id == "org-a" and run_id == RUN_A

        monkeypatch.setattr(runner, "run_exists", fake_run_exists)
        view_a = sandboxes.DockerSandboxView(EvalRunSettings(), org_id="org-a")
        view_b = sandboxes.DockerSandboxView(EvalRunSettings(), org_id="org-b")
        labels = {"signalpilot.eval": "1", "signalpilot.eval.run": RUN_A}
        try:
            assert await view_a._owns(labels) is True
            assert await view_b._owns(labels) is False
            assert await view_a._owns({"signalpilot.eval": "1"}) is False
        finally:
            await view_a.aclose()
            await view_b.aclose()

    def test_inventory_route_passes_the_callers_org(self) -> None:
        captured: list[str] = []

        class _View:
            async def inventory(self):
                return {
                    "backend": "vercel",
                    "live": True,
                    "sandboxes": [],
                    "namespace": "",
                    "message": "",
                    "supports_live_logs": True,
                }

            async def aclose(self):
                return None

        def _factory(org_id: str):
            captured.append(org_id)
            return _View()

        with patch.object(sandboxes, "get_sandbox_view", _factory):
            with _client("org-b") as client:
                assert client.get("/api/evals/sandboxes").status_code == 200
        assert captured == ["org-b"]


# Verify no secret leakage.


class TestNoSecretLeakage:
    """Every sandbox response, over a pod whose spec and messages carry real
    credentials. Nothing but the digest may survive."""

    _SECRETS = (OAUTH_TOKEN, ANTHROPIC_KEY, MCP_KEY_B64, "sp-live-secret")

    def _assert_clean(self, body: str) -> None:
        for secret in self._SECRETS:
            assert secret not in body, f"leaked {secret[:12]}… in response"

    def test_log_stream_is_clean(self) -> None:

        class _View:
            async def stream_logs(self, name, *, tail_lines):
                yield "log", f"claude booting with ANTHROPIC_API_KEY={ANTHROPIC_KEY}\n"
                yield "log", f"mcp config {MCP_KEY_B64}\n"
                yield "end", "sandbox-exited"

            async def aclose(self):
                return None

        with patch.object(sandboxes, "get_sandbox_view", lambda org_id: _View()):
            with _client("org-a") as client:
                text = client.get(f"/api/evals/sandboxes/{POD_A}/logs/stream").text
        self._assert_clean(text)
        assert "claude booting" in text


class _LockedSemaphore:
    def locked(self) -> bool:
        return True


# Verify live log stream.


class TestLogStream:
    def test_stream_emits_open_logs_and_end(self) -> None:
        closed: list[bool] = []

        class _View:
            async def stream_logs(self, name, *, tail_lines):
                assert tail_lines == 50
                yield "log", "line one\n"
                yield "end", "sandbox-exited"

            async def aclose(self):
                closed.append(True)

        with patch.object(sandboxes, "get_sandbox_view", lambda org_id: _View()):
            with _client("org-a") as client:
                resp = client.get(f"/api/evals/sandboxes/{POD_A}/logs/stream?tail=50")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        events = [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]
        assert [e["type"] for e in events] == ["open", "log", "end"]
        assert events[-1]["reason"] == "sandbox-exited"
        # The view is released even on a clean end. no leaked cluster client.
        assert closed == [True]

    def test_stream_terminates_when_the_view_errors(self) -> None:

        class _View:
            async def stream_logs(self, name, *, tail_lines):
                yield "log", "starting\n"
                raise RuntimeError("apiserver went away")

            async def aclose(self):
                return None

        with patch.object(sandboxes, "get_sandbox_view", lambda org_id: _View()):
            with _client("org-a") as client:
                resp = client.get(f"/api/evals/sandboxes/{POD_A}/logs/stream")
        events = [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]
        assert events[-1]["type"] == "end"
        assert events[-1]["reason"] == "stream-error"

    def test_bad_sandbox_name_is_rejected_before_any_cluster_call(self) -> None:
        called: list[str] = []
        with patch.object(sandboxes, "get_sandbox_view", lambda org_id: called.append(org_id)):
            with _client("org-a") as client:
                resp = client.get("/api/evals/sandboxes/not-a-pod-name/logs/stream")
        assert resp.status_code == 400
        assert called == []

    def test_tail_is_bounded(self) -> None:
        with _client("org-a") as client:
            assert client.get(f"/api/evals/sandboxes/{POD_A}/logs/stream?tail=99999").status_code == 422
            assert client.get(f"/api/evals/sandboxes/{POD_A}/logs/stream?tail=0").status_code == 422

    def test_concurrent_streams_are_capped(self, monkeypatch) -> None:
        from gateway.api import eval_sandboxes

        monkeypatch.setattr(eval_sandboxes, "_log_stream_semaphore", _LockedSemaphore())
        with _client("org-a") as client:
            resp = client.get(f"/api/evals/sandboxes/{POD_A}/logs/stream")
        assert resp.status_code == 429
        assert resp.headers.get("Retry-After") == "15"

    async def test_docker_stream_refuses_a_container_this_org_does_not_own(self, monkeypatch) -> None:
        async def fake_run_exists(org_id: str, run_id: str) -> bool:
            return False  # org-b owns nothing

        monkeypatch.setattr(runner, "run_exists", fake_run_exists)
        view = sandboxes.DockerSandboxView(EvalRunSettings(), org_id="org-b")
        with patch.object(
            sandboxes.DockerSandboxView,
            "_list_raw",
            AsyncMock(return_value=[{"Id": "a" * 64, "Labels": {"signalpilot.eval.run": RUN_A}}]),
        ):
            out = [item async for item in view.stream_logs("a" * 12, tail_lines=10)]
        await view.aclose()
        assert out == [("end", "not-found")]
