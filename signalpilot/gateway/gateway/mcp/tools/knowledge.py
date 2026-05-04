"""Knowledge Base MCP tools: get_knowledge, search_knowledge, propose_knowledge."""

from __future__ import annotations

import asyncio
import json

from gateway.errors.mcp import sanitize_mcp_error
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _store_session
from gateway.mcp.server import mcp
from gateway.models.knowledge import KnowledgeCategory, KnowledgeDoc, KnowledgeDocCreate, KnowledgeScope

_BASELINE_CATEGORIES = ("understanding", "conventions")
_TASK_SEARCH_CATEGORIES = ("decisions", "domain-rules", "debugging", "quirks")
_MAX_BASELINE_PROJECTS = 50
_MAX_KEYWORDS = 12
_OUTPUT_CAP_BYTES = 200 * 1024  # 200 KB
_SNIPPET_LENGTH = 200

_STOPWORDS = frozenset(
    {
        "the", "a", "an", "and", "or", "for", "in", "on", "at", "to", "of",
        "with", "by", "from", "as", "is", "it", "its", "be", "was", "are",
        "were", "not", "but", "if", "do", "did", "has", "have", "had",
        "this", "that", "these", "those", "can", "will", "would", "could",
        "should", "may", "might", "shall", "use", "using", "used",
    }
)


def _extract_keywords(task_description: str) -> list[str]:
    """Extract up to _MAX_KEYWORDS significant words from a task description."""
    tokens = task_description.split()
    keywords = [
        t.lower().strip(".,;:!?\"'()")
        for t in tokens
        if len(t) >= 3 and t.lower().strip(".,;:!?\"'()") not in _STOPWORDS
    ]
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for kw in keywords:
        if kw not in seen:
            seen.add(kw)
            unique.append(kw)
    return unique[:_MAX_KEYWORDS]


def _render_doc_section(doc: KnowledgeDoc, *, truncated: bool = False) -> str:
    scope_ref = doc.scope_ref or "(org)"
    header = f"[{doc.scope.value}:{scope_ref}][{doc.category.value}]"
    body = doc.body or ""
    if truncated:
        body = body[:500] + "\n[truncated]"
    return f"{header}\n## {doc.title}\n\n{body}\n"


def _build_output(sections: list[str]) -> str:
    combined = "\n".join(sections)
    if len(combined.encode("utf-8")) <= _OUTPUT_CAP_BYTES:
        return combined
    # Truncate from the end until under cap
    while sections and len("\n".join(sections).encode("utf-8")) > _OUTPUT_CAP_BYTES:
        sections.pop()
    return "\n".join(sections) + "\n[output truncated — use search_knowledge for full content]"


@audited_tool(mcp)
async def get_knowledge(task_description: str | None = None) -> str:
    """Load baseline org/project knowledge context. Pass task_description for task-specific docs."""
    try:
        async with _store_session() as store:
            # --- Baseline: org-level understanding + conventions ---
            org_docs = await store.list_knowledge_docs(
                scope="org",
                category=None,
                status="active",
                include_body=True,
                limit=10,
            )
            baseline_docs: list[KnowledgeDoc] = [
                d for d in org_docs if d.category.value in _BASELINE_CATEGORIES
            ]

            # --- Baseline: project-level understanding + conventions (up to 50 projects) ---
            proj_docs = await store.list_knowledge_docs(
                scope="project",
                category=None,
                status="active",
                include_body=True,
                limit=_MAX_BASELINE_PROJECTS * 2 + 50,
            )
            # Cap to _MAX_BASELINE_PROJECTS distinct projects, prefer most-recently-updated
            project_refs: list[str] = []
            seen_refs: set[str] = set()
            for d in sorted(proj_docs, key=lambda x: x.updated_at, reverse=True):
                ref = d.scope_ref or ""
                if ref not in seen_refs:
                    seen_refs.add(ref)
                    project_refs.append(ref)
                    if len(project_refs) >= _MAX_BASELINE_PROJECTS:
                        break

            for d in proj_docs:
                if d.scope_ref in seen_refs and d.category.value in _BASELINE_CATEGORIES:
                    baseline_docs.append(d)

            # Bump views fire-and-forget
            for doc in baseline_docs:
                asyncio.create_task(store.increment_knowledge_view(doc.id))

            sections = [_render_doc_section(d) for d in baseline_docs]

            # --- Task-specific search ---
            if task_description:
                keywords = _extract_keywords(task_description)
                task_docs: list[KnowledgeDoc] = []
                for kw in keywords:
                    hits = await store.search_knowledge(
                        query=kw,
                        category=None,
                        limit=5,
                        bump_view=False,
                    )
                    # Only include task-search categories
                    for doc in hits:
                        if doc.category.value in _TASK_SEARCH_CATEGORIES:
                            if not any(td.id == doc.id for td in task_docs):
                                task_docs.append(doc)
                    if len(task_docs) >= 5:
                        break

                for doc in task_docs[:5]:
                    asyncio.create_task(store.increment_knowledge_view(doc.id))
                    sections.append(_render_doc_section(doc))

            if not sections:
                return "No knowledge base content found."

            return _build_output(sections)

    except Exception as exc:
        return f"Error: {sanitize_mcp_error(str(exc))}"


@audited_tool(mcp)
async def search_knowledge(
    query: str,
    scope: str | None = None,
    scope_ref: str | None = None,
    category: str | None = None,
    limit: int = 20,
) -> str:
    """Search the knowledge base. Returns matching doc IDs, scope, category, title, and a snippet."""
    try:
        q = query.strip()
        if not q:
            return "Error: query must not be empty"
        if len(q) > 200:
            return "Error: query exceeds 200 character limit"

        async with _store_session() as store:
            docs = await store.search_knowledge(
                query=q,
                scope=scope,
                scope_ref=scope_ref,
                category=category,
                limit=max(1, min(limit, 50)),
                bump_view=True,
            )

        if not docs:
            return f'No knowledge docs found matching "{q}".'

        lines = [f"Found {len(docs)} result(s) for '{q}':\n"]
        for doc in docs:
            body = doc.body or ""
            # Find snippet around first match
            idx = body.lower().find(q.lower())
            if idx == -1:
                snippet = body[:_SNIPPET_LENGTH]
            else:
                start = max(0, idx - 50)
                snippet = body[start : start + _SNIPPET_LENGTH]
            scope_ref_display = doc.scope_ref or "(org)"
            lines.append(
                f"  id={doc.id} scope={doc.scope.value}:{scope_ref_display} "
                f"category={doc.category.value} title={doc.title}\n"
                f"  snippet: {snippet!r}\n"
            )
        return "\n".join(lines)

    except Exception as exc:
        return f"Error: {sanitize_mcp_error(str(exc))}"


@audited_tool(mcp)
async def propose_knowledge(
    scope: str,
    scope_ref: str | None,
    category: str,
    title: str,
    body: str,
    supersedes: str | None = None,
) -> str:
    """Propose a new knowledge doc. AI cannot create 'understanding' docs."""
    try:
        # Reject understanding — human-authored only
        if category == KnowledgeCategory.understanding.value:
            return (
                "Refused: 'understanding' is human-authored only. "
                "Use the REST API to create this document."
            )

        # Validate via DTO — raises pydantic.ValidationError on bad input
        payload = KnowledgeDocCreate(
            scope=KnowledgeScope(scope),
            scope_ref=scope_ref,
            category=KnowledgeCategory(category),
            title=title,
            body=body,
        )

        async with _store_session() as store:
            # Supersedes path: archive the old doc then insert
            if supersedes is not None:
                old_doc = await store.get_knowledge_doc(supersedes, include_body=False)
                if (
                    old_doc is not None
                    and old_doc.title == title
                    and old_doc.scope.value == scope
                    and old_doc.scope_ref == scope_ref
                    and old_doc.category.value == category
                ):
                    await store.archive_knowledge_doc(supersedes)

            try:
                doc = await store.insert_knowledge_doc(
                    payload,
                    user_id=None,
                    agent="propose_knowledge",
                )
            except Exception as exc:
                from gateway.store.knowledge import KnowledgeDuplicate

                if isinstance(exc, KnowledgeDuplicate):
                    existing_id = exc.existing_id
                    return json.dumps(
                        {
                            "status": "rejected_duplicate",
                            "existing_id": existing_id,
                            "message": (
                                f"Doc '{title}' already exists at {scope}:{scope_ref}. "
                                "Use REST to edit."
                            ),
                        }
                    )
                raise

        return json.dumps(
            {
                "status": "created",
                "id": doc.id,
                "doc_status": doc.status.value,
            }
        )

    except Exception as exc:
        from pydantic import ValidationError

        if isinstance(exc, ValidationError):
            return f"Error: invalid input — {exc.error_count()} validation error(s): {str(exc)[:300]}"
        return f"Error: {sanitize_mcp_error(str(exc))}"
