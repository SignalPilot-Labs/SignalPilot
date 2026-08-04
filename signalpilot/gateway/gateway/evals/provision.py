"""Provision branch providers and task connections for evaluation runs.

The pinned warehouse connection selects the provider.

- A pinned Xata connection selects ``XataBranchProvider`` for the same project.
  The pinned branch is the shared parent branch.
- Any other connection selects ``PostgresBranchProvider``.
  ``SP_EVAL_PG_ADMIN_DSN`` and ``SP_EVAL_PG_PARENT_DB`` configure this provider.

Each write task receives a temporary gateway connection that is pinned to its branch.
The system creates the connection before the agent starts.
Task cleanup deletes the connection. The reaper deletes an orphaned connection.
"""

from __future__ import annotations

import logging

from gateway.config.evals import EvalRunSettings
from gateway.models.connections import ConnectionCreate, DBType

from .branches import BranchProvider, PostgresBranchProvider, XataBranchProvider

logger = logging.getLogger(__name__)


class ProvisioningError(RuntimeError):
    """No branch provider can serve this run's write tasks. User-facing."""


async def resolve_branch_provider(
    store, cfg: dict, settings: EvalRunSettings
) -> BranchProvider:
    """Build the provider for this org's pinned warehouse connection."""
    conn_name = str(cfg.get("connection", "") or "")
    if conn_name:
        try:
            extras = await store.get_credential_extras(conn_name) or {}
        except Exception:
            extras = {}
        if extras.get("xata_project") and extras.get("branch"):
            from gateway.connectors.xata_control import XataControlClient, XataControlConfig
            from gateway.connectors.xata_creds import resolve_xata_extras

            resolved = resolve_xata_extras(extras)
            # Connection extras use xata_organization / xata_database — the
            # names the connection model persists. Reading xata_org silently
            # produced an empty org and a 404 on every control-plane call.
            org = str(resolved.get("xata_organization") or "").strip()
            if not org:
                raise ProvisioningError(
                    f"connection {conn_name!r} has no xata_organization in its extras — "
                    "recreate the connection so the control plane can be addressed"
                )
            control = XataControlClient(
                XataControlConfig(
                    api_url=str(resolved.get("xata_api_url", "https://api.xata.tech")),
                    org=org,
                    bearer_token=str(resolved.get("xata_api_key", "")),
                )
            )
            # XataControlClient only builds its httpx client in __aenter__, and
            # a run holds the provider across many awaits rather than one
            # `async with` block — so open it here and let the provider's
            # aclose() (called in the run's finally) close it.
            await control.__aenter__()
            return XataBranchProvider(
                control,
                project_id=str(resolved["xata_project"]),
                parent_branch=str(resolved["branch"]),
                database=str(resolved.get("xata_database") or "xata"),
            )

    if settings.pg_admin_dsn and settings.pg_parent_db:
        return PostgresBranchProvider(settings.pg_admin_dsn, settings.pg_parent_db)

    raise ProvisioningError(
        "no branch provider: pin a Xata connection in the eval config, or set "
        "SP_EVAL_PG_ADMIN_DSN and SP_EVAL_PG_PARENT_DB for a local Postgres warehouse"
    )


async def create_task_connection(store, *, name: str, dsn: str) -> str:
    """Register a temporary gateway connection for one write task's branch.

    The MCP pin routes the agent's governed tool calls here; dbt inside the
    pod gets the DSN directly. Named like the branch so the reaper can match
    them up without a lookup.
    """
    await store.create_connection(
        ConnectionCreate(
            name=name,
            db_type=DBType.postgres,
            connection_string=dsn,
            description="ephemeral eval task branch — deleted at task end",
            tags=["sp-eval"],
        )
    )
    return name


async def delete_task_connection(store, name: str) -> None:
    try:
        await store.delete_connection(name)
    except Exception:
        logger.warning("eval task connection %s was already gone", name)
