"""Eval-run settings for the gateway ("Evaluate Change" on knowledge entries).

Cached because no test monkeypatches these vars after import (new vars,
verified by grep at introduction — audit tests/ before adding more).

Class A vars managed here:
    SP_EVAL_RUNNER_IMAGE       — docker image with the claude CLI; feature disabled when unset
    SP_EVAL_DOCKER_SOCKET      — Docker Engine socket path mounted into the gateway
    SP_EVAL_DOCKER_NETWORK     — network eval containers join (must reach the gateway)
    SP_EVAL_MCP_URL            — MCP URL eval containers use to reach this gateway
    SP_EVAL_CLAUDE_TOKEN       — CLAUDE_CODE_OAUTH_TOKEN passed to eval containers
    SP_EVAL_ANTHROPIC_KEY      — alternative: ANTHROPIC_API_KEY for eval containers
    SP_EVAL_TIMEOUT_SECONDS    — per-question container timeout
    SP_EVAL_PROJECTS_DIR       — root allowed for local-path eval sets (mounted ro)
    SP_EVAL_K8S_NAMESPACE_PREFIX — namespace prefix for eval pods in cloud mode

SP_EVAL_DOCKER_* apply to local mode only. In cloud mode eval workloads run as
Kubernetes pods and the Docker socket is never opened (gateway/evals/backends.py).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field

from ._base import _GatewaySettingsBase


class EvalRunSettings(_GatewaySettingsBase):
    """Typed eval-run configuration read from process environment at instantiation."""

    runner_image: str = Field("", alias="SP_EVAL_RUNNER_IMAGE")
    docker_socket: str = Field("/var/run/docker.sock", alias="SP_EVAL_DOCKER_SOCKET")
    docker_network: str = Field("signalpilot_default", alias="SP_EVAL_DOCKER_NETWORK")
    mcp_url: str = Field("http://gateway:3300/mcp", alias="SP_EVAL_MCP_URL")
    claude_token_raw: str = Field("", alias="SP_EVAL_CLAUDE_TOKEN")
    # Fallback used by the local trap-arena harness (benchmark/.env).
    claude_key_1: str = Field("", alias="CLAUDE_KEY_1")
    anthropic_key: str = Field("", alias="SP_EVAL_ANTHROPIC_KEY")
    timeout_seconds: int = Field(600, alias="SP_EVAL_TIMEOUT_SECONDS")
    projects_dir: str = Field("/eval-projects", alias="SP_EVAL_PROJECTS_DIR")
    # ── Setup-state containers (eval-format.md §setup) ──────────────────
    # Host path corresponding to the /eval-projects mount, so local-path eval
    # repos can be bind-mounted into setup containers (docker binds resolve
    # against the HOST, not the gateway container).
    projects_host_dir: str = Field("", alias="SP_EVAL_PROJECTS_HOST_DIR")
    # Host root for manifest `setup.mounts` entries (external dbt trees etc.).
    setup_host_root: str = Field("", alias="SP_EVAL_SETUP_HOST_ROOT")
    setup_timeout_seconds: int = Field(1800, alias="SP_EVAL_SETUP_TIMEOUT_SECONDS")
    # ── Cloud (Kubernetes) execution ────────────────────────────────────
    # Namespace prefix for eval pods. Defaults to the notebook tenant prefix so
    # eval pods land in the org's existing namespace, which already has the
    # RoleBinding, NetworkPolicies, quota and LimitRange.
    #
    # A dedicated prefix is cleaner (eval pods stop sharing the notebook
    # ResourceQuota) but is NOT usable as-is: rule 5 of
    # deploy/k8s/admission/restrict-rbac-writes-* pins the
    # signalpilot.dev/tenant label to namespaces named sp-nb-*, so a differently
    # named namespace is rejected at CREATE. Changing this requires widening
    # that policy's tenantPrefix in the same deploy.
    k8s_namespace_prefix: str = Field("sp-nb", alias="SP_EVAL_K8S_NAMESPACE_PREFIX")

    @property
    def enabled(self) -> bool:
        return bool(self.runner_image)

    @property
    def claude_token(self) -> str:
        return self.claude_token_raw or self.claude_key_1


@lru_cache(maxsize=1)
def get_eval_run_settings() -> EvalRunSettings:
    """Return cached EvalRunSettings instance."""
    return EvalRunSettings()
