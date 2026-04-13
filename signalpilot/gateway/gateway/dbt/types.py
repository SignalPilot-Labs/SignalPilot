"""
Data shapes for dbt project discovery.

These are pure dataclasses with no behavior — the scanner builds them, the
formatters render them, and the cache hashes them. Keep this file
implementation-free so the public API stays small and the dependency graph
stays one-way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ModelStatus(str, Enum):
    """Lifecycle status of a dbt model relative to its yml contract."""

    COMPLETE = "complete"      # .sql exists and looks substantive
    STUB = "stub"              # .sql exists but is trivial / unfinished / unbalanced
    MISSING = "missing"        # yml defines the model but no .sql exists
    ORPHAN = "orphan"          # .sql exists but no yml entry — unmanaged model

    def is_actionable(self) -> bool:
        """True if the agent needs to do work on this model."""
        return self in (ModelStatus.MISSING, ModelStatus.STUB)


@dataclass
class ColumnSpec:
    """A single column from a yml `columns:` block."""

    name: str
    data_type: Optional[str] = None
    description: Optional[str] = None
    tests: list[str] = field(default_factory=list)


@dataclass
class ModelInfo:
    """One dbt model. May be defined in yml, or sql, or both."""

    name: str
    yml_path: Optional[str] = None      # relative to project_dir
    sql_path: Optional[str] = None      # relative to project_dir
    status: ModelStatus = ModelStatus.MISSING
    description: Optional[str] = None
    materialization: Optional[str] = None
    columns: list[ColumnSpec] = field(default_factory=list)
    refs_yml: list[str] = field(default_factory=list)      # refs declared in yml
    refs_sql: list[str] = field(default_factory=list)      # refs found in sql ({{ ref('x') }})
    sources_yml: list[tuple[str, str]] = field(default_factory=list)  # (source_name, table) pairs in yml
    sources_sql: list[tuple[str, str]] = field(default_factory=list)  # source() calls in sql
    tests: list[str] = field(default_factory=list)         # model-level tests
    unique_key: Optional[str] = None                        # first column with `unique` test
    sql_size: int = 0                                       # bytes
    tags: list[str] = field(default_factory=list)
    config: dict = field(default_factory=dict)              # yml-level config block
    directory: str = ""                                     # relative directory ("models/staging" etc.)

    @property
    def all_refs(self) -> list[str]:
        """Union of yml-declared and sql-extracted refs, deduped while preserving order."""
        seen: set[str] = set()
        result: list[str] = []
        for ref in self.refs_sql + self.refs_yml:
            if ref not in seen:
                seen.add(ref)
                result.append(ref)
        return result

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]


@dataclass
class SourceInfo:
    """A `source('name', 'table')` declaration from a yml `sources:` block."""

    name: str                                  # source name (the namespace)
    yml_path: Optional[str] = None
    schema: Optional[str] = None
    database: Optional[str] = None
    description: Optional[str] = None
    tables: list[str] = field(default_factory=list)
    table_descriptions: dict[str, str] = field(default_factory=dict)


@dataclass
class MacroInfo:
    """A `{% macro %}` declaration from a file under macros/."""

    name: str
    file_path: str                             # relative to project_dir
    signature: Optional[str] = None            # raw arg string between parens, e.g. "amount, divisor=100"
    description: Optional[str] = None          # leading comment block, if any


@dataclass
class ParseError:
    """A non-fatal error encountered while scanning a single file."""

    file_path: str
    error: str


@dataclass
class ProjectMap:
    """Top-level project view. Built by inventory.scan_project()."""

    project_name: str
    project_dir: str

    project_yml_present: bool = False
    profiles_yml_present: bool = False
    packages_yml_present: bool = False
    packages: list[str] = field(default_factory=list)

    models: dict[str, ModelInfo] = field(default_factory=dict)   # by model name
    sources: dict[str, SourceInfo] = field(default_factory=dict) # by source name
    macros: dict[str, MacroInfo] = field(default_factory=dict)   # by macro name

    work_order: list[str] = field(default_factory=list)          # actionable models in topological order
    cycles: list[list[str]] = field(default_factory=list)        # any ref cycles among actionable models
    unresolved_refs: dict[str, list[str]] = field(default_factory=dict)  # model -> refs that don't resolve

    parse_errors: list[ParseError] = field(default_factory=list)
    # Each dict has keys: file (str), line (int), match (str).
    # Heuristic only — does not handle all SQL string literal edge cases.
    current_date_warnings: list[dict] = field(default_factory=list)
    # Each dict has keys: file (str), line (int), match (str), partition_by (str|None), order_by (str|None).
    # Flags ROW_NUMBER() OVER (...) calls where ORDER BY does not uniquely identify rows.
    nondeterministic_warnings: list[dict] = field(default_factory=list)
    scan_time_ms: float = 0.0

    # Counts (cheap to access in formatters)
    @property
    def model_count(self) -> int:
        return len(self.models)

    @property
    def missing_count(self) -> int:
        return sum(1 for m in self.models.values() if m.status == ModelStatus.MISSING)

    @property
    def stub_count(self) -> int:
        return sum(1 for m in self.models.values() if m.status == ModelStatus.STUB)

    @property
    def complete_count(self) -> int:
        return sum(1 for m in self.models.values() if m.status == ModelStatus.COMPLETE)

    @property
    def orphan_count(self) -> int:
        return sum(1 for m in self.models.values() if m.status == ModelStatus.ORPHAN)

    @property
    def actionable_count(self) -> int:
        return self.missing_count + self.stub_count

    def models_by_directory(self) -> dict[str, list[ModelInfo]]:
        """Group models by their parent directory (e.g., 'models/staging')."""
        groups: dict[str, list[ModelInfo]] = {}
        for m in self.models.values():
            groups.setdefault(m.directory or "models", []).append(m)
        for k in groups:
            groups[k].sort(key=lambda m: (m.status != ModelStatus.MISSING, m.status != ModelStatus.STUB, m.name))
        return dict(sorted(groups.items()))


@dataclass
class ValidationResult:
    """Result of running `dbt parse` against a project."""

    success: bool
    parse_time_ms: float
    error_count: int
    warning_count: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    orphan_patches: list[str] = field(default_factory=list)  # yml entries with no matching node
    degradation_mode: str = "ok"   # ok | dbt_not_installed | profile_missing | parse_failed | manifest_missing
    raw_stdout: str = ""
    raw_stderr: str = ""
