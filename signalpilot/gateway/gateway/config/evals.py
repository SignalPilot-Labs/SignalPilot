"""Eval-run settings for the gateway ("Evaluate Change" on knowledge entries).

Cached because no test monkeypatches these vars after import (new vars,
verified by grep at introduction: audit tests/ before adding more).

Class A vars managed here:
    SP_EVAL_ALLOWED_ORGS: orgs allowed to use the eval feature at all
    SP_EVAL_RUNNER_IMAGE: docker image with the claude CLI; feature disabled when unset
    SP_EVAL_DOCKER_SOCKET: Docker Engine socket path mounted into the gateway
    SP_EVAL_DOCKER_NETWORK: network eval containers join (must reach the gateway)
    SP_EVAL_MCP_URL: MCP URL eval containers use to reach this gateway
    SP_EVAL_CLAUDE_TOKEN: CLAUDE_CODE_OAUTH_TOKEN passed to eval containers
    SP_EVAL_ANTHROPIC_KEY: alternative: ANTHROPIC_API_KEY for eval containers
    SP_EVAL_TIMEOUT_SECONDS: per-question container timeout
    SP_EVAL_PROJECTS_DIR: root allowed for local-path eval sets (mounted ro)

SP_EVAL_DOCKER_* apply to local mode only. In cloud mode eval workloads run on
Vercel sandboxes and the Docker socket is never opened (gateway/evals/backends.py).
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
    # requiring it would break development for no tenancy gained. Deployment
    # mode is read at call time so the allowlist follows the mode, not import order.
    allowed_orgs_raw: str = Field("", alias="SP_EVAL_ALLOWED_ORGS")

    runner_image: str = Field("", alias="SP_EVAL_RUNNER_IMAGE")
    setup_image: str = Field("", alias="SP_EVAL_SETUP_IMAGE")
    # "" = docker in local mode; unusable in cloud mode (the run fails with a
    # clear error). "vercel" = ephemeral Vercel sandbox VMs (needs VERCEL_*
    # credentials) — required in cloud mode. There is no cluster backend anymore.
    execution_backend: str = Field("", alias="SP_EVAL_EXECUTION_BACKEND")
    docker_socket: str = Field("/var/run/docker.sock", alias="SP_EVAL_DOCKER_SOCKET")
    docker_network: str = Field("signalpilot_eval_runtime", alias="SP_EVAL_DOCKER_NETWORK")
    mcp_url: str = Field("http://gateway:3300/mcp", alias="SP_EVAL_MCP_URL")
    claude_token_raw: str = Field("", alias="SP_EVAL_CLAUDE_TOKEN")
    # Fallback used by the local eval harness (benchmark/.env).
    claude_key_1: str = Field("", alias="CLAUDE_KEY_1")
    anthropic_key: str = Field("", alias="SP_EVAL_ANTHROPIC_KEY")
    # KEY=VALUE lines merged into every question container (see project_env).
    project_env_raw: str = Field("", alias="SP_EVAL_PROJECT_ENV")
    timeout_seconds: int = Field(600, alias="SP_EVAL_TIMEOUT_SECONDS")
    projects_dir: str = Field("/eval-projects", alias="SP_EVAL_PROJECTS_DIR")
    # Setup-state containers (eval-format.md §setup).
    # Host path corresponding to the /eval-projects mount, so local-path eval
    # repos can be bind-mounted into setup containers (docker binds resolve
    # against the HOST, not the gateway container).
    projects_host_dir: str = Field("", alias="SP_EVAL_PROJECTS_HOST_DIR")
    # Host root for manifest `setup.mounts` entries (external dbt trees etc.).
    setup_host_root: str = Field("", alias="SP_EVAL_SETUP_HOST_ROOT")
    setup_timeout_seconds: int = Field(1800, alias="SP_EVAL_SETUP_TIMEOUT_SECONDS")
    # Evidence store for S3 or MinIO.
    # The store contains transcripts, setup logs, table captures, and export archives.
    # Separate credentials prevent MinIO credentials from reaching BYOK or Redshift integrations.
    # An empty bucket disables runs because each run requires durable evidence storage.
    s3_bucket: str = Field("", alias="SP_EVAL_S3_BUCKET")
    s3_endpoint: str = Field("", alias="SP_EVAL_S3_ENDPOINT")
    # Optional GET-only proxy address embedded in URLs handed to eval sandboxes.
    # Gateway reads/writes continue to use s3_endpoint on the private network.
    s3_runner_endpoint: str = Field("", alias="SP_EVAL_S3_RUNNER_ENDPOINT")
    s3_region: str = Field("us-east-1", alias="SP_EVAL_S3_REGION")
    s3_access_key: str = Field("", alias="SP_EVAL_S3_ACCESS_KEY")
    s3_secret_key: str = Field("", alias="SP_EVAL_S3_SECRET_KEY")

    # Regression notifications.
    # An empty SMTP host selects SES in the configured region.
    smtp_host: str = Field("", alias="SP_EVAL_SMTP_HOST")
    smtp_port: int = Field(1025, alias="SP_EVAL_SMTP_PORT")
    notify_from: str = Field("evals@signalpilot.dev", alias="SP_EVAL_NOTIFY_FROM")
    # This relative decrease from the trailing median identifies a regression.
    # The notification includes the measured value and the trailing median.
    regression_drop_pct: float = Field(10.0, alias="SP_EVAL_REGRESSION_DROP_PCT")

    # Local branch provider for Docker Desktop or self-hosted PostgreSQL.
    # When the pinned warehouse connection is not a Xata connection, write
    # tasks fork branches as databases on this admin DSN:
    #   CREATE DATABASE eval_name TEMPLATE <SP_EVAL_PG_PARENT_DB>
    pg_admin_dsn: str = Field("", alias="SP_EVAL_PG_ADMIN_DSN")
    pg_parent_db: str = Field("", alias="SP_EVAL_PG_PARENT_DB")

    # Run model.
    # This limit controls node capacity and model cost for concurrent task containers.
    max_parallel_tasks: int = Field(4, alias="SP_EVAL_MAX_PARALLEL_TASKS")
    # Enforce these quotas before the branch fork.
    max_eval_branches: int = Field(50, alias="SP_EVAL_MAX_BRANCHES")
    branch_storage_delta_bytes: int = Field(
        5 * 1024**3, alias="SP_EVAL_BRANCH_STORAGE_DELTA_BYTES"
    )
    artifact_bytes_per_run: int = Field(1024**3, alias="SP_EVAL_ARTIFACT_BYTES_PER_RUN")
    # Reject a full capture that exceeds this limit. Do not truncate the capture.
    capture_full_max_bytes: int = Field(256 * 1024**2, alias="SP_EVAL_CAPTURE_FULL_MAX_BYTES")

    # Cloud-mode image digest must be sha256 + exactly 64 lowercase hex chars,
    # matching the guarantee SP_NOTEBOOK_VERCEL_IMAGE carries.
    _DIGEST_RE = re.compile(r"@sha256:[0-9a-f]{64}$")

    @field_validator("runner_image", "setup_image", mode="after")
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
                "Eval runner and setup images must reference a digest in cloud mode "
                "(e.g. your-registry/eval-runner@sha256:<64-hex>). "
                "Floating tags like ':latest' are not allowed. "
                "Look up the digest with: crane digest <image> OR "
                "docker buildx imagetools inspect <image>"
            )
        return v

    @field_validator("execution_backend", mode="after")
    @classmethod
    def _known_backend(cls, v: str) -> str:
        if v not in ("", "vercel"):
            raise ValueError(
                f"SP_EVAL_EXECUTION_BACKEND must be empty or 'vercel', got {v!r}"
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

    @property
    def project_env(self) -> dict[str, str]:
        """Return additional environment variables for task containers.

        Use newline-separated or comma-separated KEY=VALUE entries.
        The secret channel sends warehouse credentials to the checked-out dbt project.
        The dbt profiles.yml file reads the credentials through env_var.
        Use read-only credentials because the container executes model-authored commands.
        """
        out: dict[str, str] = {}
        raw = (self.project_env_raw or "").replace(",", "\n")
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key:
                out[key] = value.strip()
        return out


@lru_cache(maxsize=1)
def get_eval_run_settings() -> EvalRunSettings:
    """Return cached EvalRunSettings instance."""
    return EvalRunSettings()
