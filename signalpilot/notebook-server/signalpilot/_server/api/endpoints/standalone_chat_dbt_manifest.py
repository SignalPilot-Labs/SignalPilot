"""Seed a chat checkout with the project's compiled dbt manifest.

The frozen checkout is pulled from the workspace source snapshot, which has
no ``target/`` directory. The chat agent cannot build one itself: the
sandbox has no warehouse credentials and ``dbt parse`` usually needs
``dbt deps`` first. The gateway's dbt map already compiles every branch
revision and stores the manifest, so copy the newest successful one into
``<dbt project>/target/manifest.json``. The verifier agents read it for
resource types, materializations, and raw SQL.

Which directory inside the checkout is the dbt project comes from the dbt map
row. Rows compiled before that column existed carry NULL, so fall back to
asking the gateway for the org's configured directory; guessing from the tree
only works when the repo holds exactly one dbt project, and several of ours
hold more.

Best effort: a project without a successful dbt map still gets a usable
checkout, just without ``target/``.
"""

from __future__ import annotations

import gzip
import os
from typing import TYPE_CHECKING

import httpx

from signalpilot import _loggers

if TYPE_CHECKING:
    from pathlib import Path

LOGGER = _loggers.sp_logger()

_MAX_MANIFEST_BYTES = 512 * 1024 * 1024


def _configured_dbt_project_dir(
    *, project_id: str, branch: str, gateway_url: str, gateway_token: str
) -> str | None:
    """The org's configured dbt project directory, for manifest rows that do
    not record one. Returns None when the gateway has no answer."""
    try:
        response = httpx.get(
            f"{gateway_url}/api/workspace-projects/{project_id}/dbt-project-dir",
            params={"branch": branch},
            headers={"Authorization": f"Bearer {gateway_token}"},
            timeout=15.0,
        )
        response.raise_for_status()
        return response.json().get("dbt_project_dir")
    except Exception:
        LOGGER.warning(
            "Could not resolve the configured dbt project dir project_id=%s",
            project_id,
            exc_info=True,
        )
        return None


def _dbt_project_directory(
    checkout: Path, configured: str | None
) -> Path | None:
    """The dbt project root inside the checkout: the directory the dbt map
    compiled, else the root or the single child holding dbt_project.yml."""
    if configured:
        candidate = (checkout / configured).resolve()
        if candidate != checkout and checkout not in candidate.parents:
            return None
        return candidate if (candidate / "dbt_project.yml").is_file() else None
    if (checkout / "dbt_project.yml").is_file():
        return checkout
    found = [p.parent for p in checkout.glob("*/dbt_project.yml")]
    return found[0] if len(found) == 1 else None


def seed_dbt_manifest(
    checkout: Path,
    *,
    project_id: str,
    branch: str,
    gateway_url: str,
    gateway_token: str,
) -> Path | None:
    """Write target/manifest.json into the checkout. Returns the path, or
    None when there is no manifest to seed. Never raises."""
    try:
        return _seed(
            checkout.resolve(),
            project_id=project_id,
            branch=branch,
            gateway_url=gateway_url,
            gateway_token=gateway_token,
        )
    except Exception:
        LOGGER.warning(
            "Could not seed dbt manifest project_id=%s branch=%s",
            project_id,
            branch,
            exc_info=True,
        )
        return None


def _seed(
    checkout: Path,
    *,
    project_id: str,
    branch: str,
    gateway_url: str,
    gateway_token: str,
) -> Path | None:
    response = httpx.get(
        f"{gateway_url}/api/workspace-projects/{project_id}/dbt-map/manifest",
        params={"branch": branch},
        headers={"Authorization": f"Bearer {gateway_token}"},
        timeout=15.0,
    )
    if response.status_code == 404:
        LOGGER.info(
            "No compiled dbt manifest to seed project_id=%s branch=%s",
            project_id,
            branch,
        )
        return None
    response.raise_for_status()
    body = response.json()
    manifest_url = str(body.get("manifest_url") or "")
    if not manifest_url:
        return None

    configured = body.get("dbt_project_dir")
    if configured is None:
        # Compiled before the dbt map recorded its directory (migration 0037).
        configured = _configured_dbt_project_dir(
            project_id=project_id,
            branch=branch,
            gateway_url=gateway_url,
            gateway_token=gateway_token,
        )
    project_dir = _dbt_project_directory(checkout, configured)
    if project_dir is None:
        LOGGER.warning(
            "dbt manifest not seeded: no dbt project directory project_id=%s dir=%r",
            project_id,
            configured,
        )
        return None
    target = project_dir / "target" / "manifest.json"
    if target.is_file():
        return target

    compressed = httpx.get(manifest_url, timeout=60.0)
    compressed.raise_for_status()
    manifest = gzip.decompress(compressed.content)
    if len(manifest) > _MAX_MANIFEST_BYTES:
        raise ValueError(f"dbt manifest too large: {len(manifest)} bytes")

    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".json.partial")
    partial.write_bytes(manifest)
    os.replace(partial, target)
    LOGGER.info(
        "Seeded dbt manifest project_id=%s revision=%s bytes=%s path=%s",
        project_id,
        body.get("revision"),
        len(manifest),
        target,
    )
    return target
