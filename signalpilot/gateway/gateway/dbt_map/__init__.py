"""dbt map pipeline: sandbox-side `dbt parse` -> centrally stored lineage.

The gateway never runs dbt itself — compiles execute on Vercel sandboxes and
only the resulting artifacts (gzipped manifest.json + distilled graph) come
back, landing in workspace S3 with a gateway_dbt_manifests index row.
"""

from .runner import schedule_compile

__all__ = ["schedule_compile"]
