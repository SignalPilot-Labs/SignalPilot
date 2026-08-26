"""dbt --version output parsing — dependency-free so tests can load this
module standalone (gateway/tests/test_fusion_compat.py loads it by file path).

dbt-core prints a multi-line block ("Core:" / "  - installed: 1.8.2");
dbt Fusion prints a single "dbt-fusion 2.0.0-preview.NNN" line.
"""

from __future__ import annotations


def parse_dbt_version(stdout: str) -> str | None:
    """Version string from `dbt --version` output, or None.

    Fusion versions are prefixed "fusion-" so downstream can distinguish
    engines without a separate field.
    """
    for line in stdout.splitlines():
        lowered = line.lower()
        if "installed" in lowered or "core" in lowered or "fusion" in lowered:
            version = None
            for part in line.strip().split():
                if part and part[0].isdigit():
                    version = part
                    break
            if version:
                if "fusion" in lowered:
                    return f"fusion-{version}"
                return version
    return None
