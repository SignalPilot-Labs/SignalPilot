"""Pydantic DTOs for the Knowledge Base feature."""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,118}[a-z0-9])?$")

# Category × scope whitelist
_SCOPE_CATEGORIES: dict[str, set[str]] = {
    "org": {"understanding", "conventions"},
    "project": {"understanding", "conventions", "decisions", "domain-rules", "debugging"},
    "connection": {"quirks"},
}


class KnowledgeScope(str, Enum):  # noqa: UP042 — (str,Enum) keeps str(X.A)=='X.A'; StrEnum returns 'A' and breaks f-string/log output
    org = "org"
    project = "project"
    connection = "connection"


class KnowledgeCategory(str, Enum):  # noqa: UP042 — (str,Enum) keeps str(X.A)=='X.A'; StrEnum returns 'A' and breaks f-string/log output
    understanding = "understanding"
    conventions = "conventions"
    decisions = "decisions"
    domain_rules = "domain-rules"
    debugging = "debugging"
    quirks = "quirks"


class KnowledgeStatus(str, Enum):  # noqa: UP042 — (str,Enum) keeps str(X.A)=='X.A'; StrEnum returns 'A' and breaks f-string/log output
    active = "active"
    pending = "pending"
    archived = "archived"


class KnowledgeDoc(BaseModel):
    id: str
    org_id: str
    scope: KnowledgeScope
    scope_ref: str | None
    category: KnowledgeCategory
    title: str
    body: str | None = None
    status: KnowledgeStatus
    bytes: int
    view_count: int
    created_at: float
    updated_at: float
    created_by: str | None
    updated_by: str | None
    proposed_by_agent: str | None


class KnowledgeDocCreate(BaseModel):
    scope: KnowledgeScope
    scope_ref: str | None = None
    category: KnowledgeCategory
    title: str = Field(..., min_length=1, max_length=120)
    body: str = Field(..., min_length=1)
    status: KnowledgeStatus = KnowledgeStatus.active

    @field_validator("title")
    @classmethod
    def validate_title_slug(cls, v: str) -> str:
        if not _SLUG_RE.match(v):
            raise ValueError(
                "title must be lowercase alphanumeric with hyphens, no leading/trailing hyphens"
            )
        return v

    @model_validator(mode="after")
    def validate_scope_category_and_ref(self) -> KnowledgeDocCreate:
        scope_val = self.scope.value if hasattr(self.scope, "value") else self.scope
        cat_val = self.category.value if hasattr(self.category, "value") else self.category

        allowed = _SCOPE_CATEGORIES.get(scope_val, set())
        if cat_val not in allowed:
            raise ValueError(
                f"Category '{cat_val}' is not allowed for scope '{scope_val}'. "
                f"Allowed: {sorted(allowed)}"
            )

        if scope_val == "org":
            if self.scope_ref is not None:
                raise ValueError("scope_ref must be None when scope is 'org'")
        else:
            if not self.scope_ref:
                raise ValueError(f"scope_ref is required for scope '{scope_val}'")
            if len(self.scope_ref) > 200:
                raise ValueError("scope_ref must be <= 200 characters")

        return self


class KnowledgeDocUpdate(BaseModel):
    body: str = Field(..., min_length=1)


class KnowledgeEdit(BaseModel):
    id: str
    doc_id: str
    org_id: str
    body_before: str
    bytes_before: int
    edited_at: float
    edited_by: str | None
    edit_kind: str


class KnowledgeUsage(BaseModel):
    org_id: str
    active_docs: int
    active_bytes: int
    storage_limit_bytes: int  # 0 = unlimited
    storage_limit_mb: int  # 0 = unlimited
