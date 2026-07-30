"""Eval-run settings for the gateway ("Evaluate Change" on knowledge entries).

Cached because no test monkeypatches these vars after import (new vars,
verified by grep at introduction — audit tests/ before adding more).

Class A vars managed here:
    SP_EVAL_ALLOWED_ORGS       — orgs allowed to use the eval feature at all
    SP_EVAL_RUNNER_IMAGE       — docker image with the claude CLI; feature disabled when unset
    SP_EVAL_DOCKER_SOCKET      — Docker Engine socket path mounted into the gateway
    SP_EVAL_DOCKER_NETWORK     — network eval containers join (must reach the gateway)
    SP_EVAL_MCP_URL            — MCP URL eval containers use to reach this gateway
    SP_EVAL_CLAUDE_TOKEN       — CLAUDE_CODE_OAUTH_TOKEN passed to eval containers
    SP_EVAL_ANTHROPIC_KEY      — alternative: ANTHROPIC_API_KEY for eval containers
    SP_EVAL_TIMEOUT_SECONDS    — per-question container timeout
    SP_EVAL_PROJECTS_DIR       — root allowed for local-path eval sets (mounted ro)
    SP_EVAL_K8S_NAMESPACE_PREFIX — namespace prefix for eval pods in cloud mode
    SP_EVAL_CPU_REQUEST / SP_EVAL_CPU_LIMIT             — eval pod cpu sizing
    SP_EVAL_MEMORY_REQUEST / SP_EVAL_MEMORY_LIMIT       — eval pod memory sizing
    SP_EVAL_EPHEMERAL_REQUEST / SP_EVAL_EPHEMERAL_LIMIT — eval pod scratch sizing

SP_EVAL_DOCKER_* apply to local mode only. In cloud mode eval workloads run as
Kubernetes pods and the Docker socket is never opened (gateway/evals/backends.py).
"""

from __future__ import annotations

import os
import re
from functools import lru_cache

from pydantic import Field, field_validator

from ._base import _GatewaySettingsBase


class EvalRunSettings(_GatewaySettingsBase):
    """Typed eval-run configuration read from process environment at instantiation."""

    # Comma-separated Clerk org ids allowed to reach the eval feature.
    #
    # Empty means DENY ALL in cloud mode: an unset allowlist is the state a fresh
    # deployment is in, and there is no org id it could safely stand for. Empty in
    # local mode allows the caller, because a local deployment is single-tenant
    # with a synthetic org id ("local") that nobody would think to enumerate here
    # — requiring it would break development for no tenancy gained. Deployment
    # mode is read at call time so the allowlist follows the mode, not import order.
    allowed_orgs_raw: str = Field("", alias="SP_EVAL_ALLOWED_ORGS")

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

    # Eval pods are sized exactly like notebook pods: they share the sandbox node
    # group, so a limit larger than that node's allocatable CPU could never be
    # honoured. Both limit:request ratios are 4, which is the namespace
    # LimitRange maxLimitRequestRatio — raising a limit without raising its
    # request in step gets the pod rejected at CREATE.
    cpu_request: str = Field("250m", alias="SP_EVAL_CPU_REQUEST")
    cpu_limit: str = Field("1", alias="SP_EVAL_CPU_LIMIT")
    memory_request: str = Field("128Mi", alias="SP_EVAL_MEMORY_REQUEST")
    memory_limit: str = Field("512Mi", alias="SP_EVAL_MEMORY_LIMIT")
    ephemeral_request: str = Field("256Mi", alias="SP_EVAL_EPHEMERAL_REQUEST")
    ephemeral_limit: str = Field("4Gi", alias="SP_EVAL_EPHEMERAL_LIMIT")

    @property
    def pod_resources(self) -> dict[str, dict[str, str]]:
        return {
            "requests": {
                "cpu": self.cpu_request,
                "memory": self.memory_request,
                "ephemeral-storage": self.ephemeral_request,
            },
            "limits": {
                "cpu": self.cpu_limit,
                "memory": self.memory_limit,
                "ephemeral-storage": self.ephemeral_limit,
            },
        }

    # Cloud-mode image digest must be sha256 + exactly 64 lowercase hex chars,
    # matching the guarantee SP_NOTEBOOK_IMAGE already carries.
    _DIGEST_RE = re.compile(r"@sha256:[0-9a-f]{64}$")

    @field_validator("runner_image", mode="after")
    @classmethod
    def _require_digest_in_cloud_mode(cls, v: str) -> str:
        """In cloud mode the eval runner image must be digest-pinned.

        This image executes untrusted eval workloads, so a floating tag would let
        what actually runs in the sandbox change without the config changing.
        Empty is allowed: it is how the feature stays disabled.
        """
        if not v:
            return v
        is_cloud = os.environ.get("SP_DEPLOYMENT_MODE", "").lower() == "cloud"
        if is_cloud and not re.search(r"@sha256:[0-9a-f]{64}$", v):
            raise ValueError(
                "SP_EVAL_RUNNER_IMAGE must reference a digest in cloud mode "
                "(e.g. your-registry/eval-runner@sha256:<64-hex>). "
                "Floating tags like ':latest' are not allowed. "
                "Look up the digest with: crane digest <image> OR "
                "docker buildx imagetools inspect <image>"
            )
        return v

    @property
    def allowed_orgs(self) -> frozenset[str]:
        """Parse SP_EVAL_ALLOWED_ORGS CSV into a frozenset of stripped, non-empty ids."""
        return frozenset(o.strip() for o in self.allowed_orgs_raw.split(",") if o.strip())

    def org_allowed(self, org_id: str | None) -> bool:
        """Whether `org_id` may use evals at all. See allowed_orgs_raw for empty-list semantics."""
        allowed = self.allowed_orgs
        if not allowed:
            return os.environ.get("SP_DEPLOYMENT_MODE", "").lower() != "cloud"
        return bool(org_id) and org_id in allowed

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
