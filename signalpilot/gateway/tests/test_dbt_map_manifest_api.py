"""dbt-map manifest endpoint: chat sandboxes seed target/manifest.json from it."""

from __future__ import annotations

import asyncio

from .test_dbt_map_api import PROJECT, harness  # pytest fixture import

MANIFEST_URL = f"/api/workspace-projects/{PROJECT}/dbt-map/manifest"


def _presign(storage):
    async def presign_get(key: str, expires_seconds: int = 3600) -> str:
        return f"https://s3.test/{key}"

    storage.presign_get = presign_get


def test_manifest_returns_the_newest_success_and_its_project_dir(harness):
    client, _graph, storage, insert = harness
    _presign(storage)
    asyncio.run(insert(revision=2, manifest_key="k/2-manifest.json.gz", dbt_project_dir="proj_dir"))
    # A newer compile that is still running must not hide the last good one.
    asyncio.run(insert(revision=3, status="running", manifest_key=None))
    resp = client.get(MANIFEST_URL)
    assert resp.status_code == 200
    body = resp.json()
    assert body["revision"] == 2
    assert body["dbt_project_dir"] == "proj_dir"
    assert body["manifest_url"] == "https://s3.test/k/2-manifest.json.gz"


def test_manifest_404_without_a_stored_manifest(harness):
    client, _graph, storage, _insert = harness
    _presign(storage)
    # The fixture row is a success without a manifest_key.
    assert client.get(MANIFEST_URL).status_code == 404
