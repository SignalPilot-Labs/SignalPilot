"""Knowledge Base MCP tools: get_knowledge, search_knowledge, propose_knowledge, archive_knowledge."""

from __future__ import annotations

import asyncio
import json

from gateway.errors.mcp import sanitize_mcp_error
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _require_mcp_admin_scope, _store_session
from gateway.mcp.server import mcp
from gateway.models.knowledge import KnowledgeCategory, KnowledgeDoc, KnowledgeDocCreate, KnowledgeScope

# context = the "God Doc": always injected into every agent's baseline.
_BASELINE_CATEGORIES = ("context",)
_TASK_SEARCH_CATEGORIES = ("decisions", "rules", "troubleshooting")
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
    overwrite: bool = False,
) -> str:
    """Create a knowledge doc, or edit an existing one in place.

    Set overwrite=True to replace the body of the doc that has the same
    scope, scope_ref, category, and title. Without overwrite, a doc whose
    key already exists is rejected as a duplicate.

    supersedes is DEPRECATED — it only ever versioned a same-key doc and
    silently no-opped otherwise. Passing any value now behaves like
    overwrite=True. To retire a doc under a different title, call
    archive_knowledge instead.
    """
    try:
        err = _require_mcp_admin_scope()
        if err:
            return err
        # Validate via DTO — raises pydantic.ValidationError on bad input
        payload = KnowledgeDocCreate(
            scope=KnowledgeScope(scope),
            scope_ref=scope_ref,
            category=KnowledgeCategory(category),
            title=title,
            body=body,
        )

        # supersedes is a deprecated alias for overwrite.
        overwrite = overwrite or supersedes is not None

        async with _store_session() as store:
            # Overwrite path: update the existing doc (matched by unique key) in
            # place. upsert_knowledge_doc appends an edit-history row and trims
            # history; it inserts if no doc with the key exists yet.
            if overwrite:
                existing = await store.get_knowledge_doc_by_key(
                    scope=scope,
                    scope_ref=scope_ref,
                    category=category,
                    title=title,
                )
                doc = await store.upsert_knowledge_doc(
                    payload,
                    user_id=None,
                    agent="propose_knowledge",
                )
                return json.dumps(
                    {
                        "status": "updated" if existing is not None else "created",
                        "id": doc.id,
                        "doc_status": doc.status.value,
                    }
                )

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
                                "Call propose_knowledge again with overwrite=true to edit it in place."
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


@audited_tool(mcp)
async def archive_knowledge(doc_id: str) -> str:
    """Archive (soft-delete) a knowledge doc by id. Archived docs are excluded from search and get_knowledge but retained for audit."""
    try:
        err = _require_mcp_admin_scope()
        if err:
            return err
        doc_id = (doc_id or "").strip()
        if not doc_id:
            return "Error: doc_id must not be empty"

        async with _store_session() as store:
            # Fetch first so we can report what was archived and detect already-archived docs.
            doc = await store.get_knowledge_doc(doc_id, include_body=False)
            if doc is None:
                return json.dumps(
                    {
                        "status": "not_found",
                        "id": doc_id,
                        "message": f"Knowledge doc '{doc_id}' not found.",
                    }
                )
            if doc.status.value == "archived":
                return json.dumps(
                    {
                        "status": "already_archived",
                        "id": doc_id,
                        "title": doc.title,
                    }
                )

            archived = await store.archive_knowledge_doc(doc_id)
            if not archived:
                return json.dumps(
                    {
                        "status": "not_found",
                        "id": doc_id,
                        "message": f"Knowledge doc '{doc_id}' not found.",
                    }
                )

        return json.dumps(
            {
                "status": "archived",
                "id": doc_id,
                "title": doc.title,
            }
        )

    except Exception as exc:
        return f"Error: {sanitize_mcp_error(str(exc))}"
