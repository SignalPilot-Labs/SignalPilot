"""
Schema annotations — Feature #16 from the feature table.

Loads YAML sidecar files with:
- Table descriptions, owners, sensitivity levels
- Column descriptions, business definitions
- PII flags with redaction rules (hash, mask, drop)
- Blocked tables that agents should never query

Annotations are stored in ~/.signalpilot/schema.yml or alongside dbt models.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


@dataclass
class ColumnAnnotation:
    """Annotations for a single column."""
    description: str = ""
    business_name: str = ""
    unit: str = ""
    pii: str | None = None  # hash, mask, drop
    sensitivity: str = "public"  # public, internal, confidential, restricted
    tags: list[str] = field(default_factory=list)


@dataclass
class TableAnnotation:
    """Annotations for a single table."""
    description: str = ""
    owner: str = ""
    sensitivity: str = "internal"
    blocked: bool = False
    tags: list[str] = field(default_factory=list)
    columns: dict[str, ColumnAnnotation] = field(default_factory=dict)


@dataclass
class SchemaAnnotations:
    """Full set of annotations for a connection."""
    connection_name: str = ""
    tables: dict[str, TableAnnotation] = field(default_factory=dict)

    @property
    def blocked_tables(self) -> list[str]:
        """List of table names that are blocked by policy."""
        return [name for name, t in self.tables.items() if t.blocked]

    @property
    def pii_columns(self) -> dict[str, str]:
        """Map of column name -> PII rule for all PII-flagged columns."""
        result = {}
        for table in self.tables.values():
            for col_name, col in table.columns.items():
                if col.pii:
                    result[col_name] = col.pii
        return result

    def get_table(self, name: str) -> TableAnnotation | None:
        """Get annotations for a table (case-insensitive)."""
        name_lower = name.lower()
        for key, val in self.tables.items():
            if key.lower() == name_lower:
                return val
        return None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for API response."""
        result: dict[str, Any] = {
            "connection_name": self.connection_name,
            "table_count": len(self.tables),
            "blocked_tables": self.blocked_tables,
            "pii_columns": self.pii_columns,
            "tables": {},
        }
        for name, table in self.tables.items():
            result["tables"][name] = {
                "description": table.description,
                "owner": table.owner,
                "sensitivity": table.sensitivity,
                "blocked": table.blocked,
                "tags": table.tags,
                "columns": {
                    col_name: {
                        "description": col.description,
                        "business_name": col.business_name,
                        "pii": col.pii,
                        "sensitivity": col.sensitivity,
                    }
                    for col_name, col in table.columns.items()
                },
            }
        return result


# TTL cache for annotations to avoid re-reading YAML on every query
_annotations_cache: dict[str, tuple[float, SchemaAnnotations]] = {}
_ANNOTATIONS_TTL = float(os.getenv("SP_ANNOTATIONS_TTL", "60"))  # seconds


def load_annotations(
    connection_name: str,
    search_paths: list[str | Path] | None = None,
) -> SchemaAnnotations:
    """Load schema annotations from YAML files (cached with TTL).

    Searches in order:
    1. Custom paths provided
    2. ~/.signalpilot/annotations/{connection_name}.yml
    3. ~/.signalpilot/schema.yml
    """
    # Check cache first (skip cache if custom search_paths provided)
    if not search_paths and connection_name in _annotations_cache:
        cached_at, cached = _annotations_cache[connection_name]
        if time.monotonic() - cached_at < _ANNOTATIONS_TTL:
            return cached

    if not HAS_YAML:
        return SchemaAnnotations(connection_name=connection_name)

    data_dir = Path(os.getenv("SP_DATA_DIR", str(Path.home() / ".signalpilot")))
    paths_to_try = []

    if search_paths:
        paths_to_try.extend(Path(p) for p in search_paths)

    paths_to_try.extend([
        data_dir / "annotations" / f"{connection_name}.yml",
        data_dir / "annotations" / f"{connection_name}.yaml",
        data_dir / "schema.yml",
        data_dir / "schema.yaml",
    ])

    for path in paths_to_try:
        if path.exists():
            try:
                result = _parse_annotation_file(path, connection_name)
                if not search_paths:
                    _annotations_cache[connection_name] = (time.monotonic(), result)
                return result
            except Exception:
                continue

    empty = SchemaAnnotations(connection_name=connection_name)
    if not search_paths:
        _annotations_cache[connection_name] = (time.monotonic(), empty)
    return empty


def invalidate_annotations_cache(connection_name: str | None = None):
    """Clear cached annotations. Call when annotations are updated."""
    if connection_name:
        _annotations_cache.pop(connection_name, None)
    else:
        _annotations_cache.clear()


def _parse_annotation_file(path: Path, connection_name: str) -> SchemaAnnotations:
    """Parse a YAML annotation file into SchemaAnnotations."""
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        return SchemaAnnotations(connection_name=connection_name)

    annotations = SchemaAnnotations(connection_name=connection_name)

    # Support both flat format and connection-scoped format
    tables_raw = raw.get("tables", {})
    if not tables_raw and connection_name in raw:
        tables_raw = raw[connection_name].get("tables", {})

    for table_name, table_raw in tables_raw.items():
        if not isinstance(table_raw, dict):
            continue

        table_ann = TableAnnotation(
            description=table_raw.get("description", ""),
            owner=table_raw.get("owner", ""),
            sensitivity=table_raw.get("sensitivity", "internal"),
            blocked=table_raw.get("blocked", False),
            tags=table_raw.get("tags", []),
        )

        columns_raw = table_raw.get("columns", {})
        for col_name, col_raw in columns_raw.items():
            if not isinstance(col_raw, dict):
                continue
            table_ann.columns[col_name] = ColumnAnnotation(
                description=col_raw.get("description", ""),
                business_name=col_raw.get("business_name", ""),
                unit=col_raw.get("unit", ""),
                pii=col_raw.get("pii"),
                sensitivity=col_raw.get("sensitivity", "public"),
                tags=col_raw.get("tags", []),
            )

        annotations.tables[table_name] = table_ann

    return annotations


def generate_skeleton(schema: dict[str, Any], connection_name: str) -> str:
    """Generate a starter schema.yml from database introspection (Feature #29).

    Takes the output of connector.get_schema() and produces a YAML skeleton
    that humans can fill in with descriptions and annotations.
    """
    lines = [
        f"# Schema annotations for {connection_name}",
        f"# Generated by SignalPilot — fill in descriptions and PII rules",
        "",
        "tables:",
    ]

    for key, table_info in schema.items():
        table_name = table_info.get("name", key)
        lines.append(f"  {table_name}:")
        lines.append(f"    description: \"\"")
        lines.append(f"    owner: \"\"")
        lines.append(f"    sensitivity: internal")
        lines.append(f"    blocked: false")
        lines.append(f"    columns:")

        for col in table_info.get("columns", []):
            col_name = col.get("name", "unknown")
            col_type = col.get("type", "")
            lines.append(f"      {col_name}:")
            lines.append(f"        description: \"\"  # {col_type}")
            # Suggest PII rules for common column names
            pii_suggestion = _suggest_pii_rule(col_name)
            if pii_suggestion:
                lines.append(f"        pii: {pii_suggestion}")

    return "\n".join(lines) + "\n"


def _suggest_pii_rule(column_name: str) -> str | None:
    """Suggest a PII redaction rule based on column name heuristics."""
    name = column_name.lower()
    # Common PII column names
    if any(term in name for term in ("email", "e_mail")):
        return "hash"
    if any(term in name for term in ("ssn", "social_security", "tax_id", "national_id")):
        return "mask"
    if any(term in name for term in ("phone", "mobile", "cell")):
        return "mask"
    if any(term in name for term in ("address", "street", "zip_code", "postal")):
        return "mask"
    if any(term in name for term in ("password", "passwd", "secret", "token")):
        return "drop"
    if any(term in name for term in ("credit_card", "card_number", "cvv")):
        return "drop"
    if any(term in name for term in ("first_name", "last_name", "full_name", "surname")):
        return "mask"
    if any(term in name for term in ("date_of_birth", "dob", "birth_date")):
        return "mask"
    return None
