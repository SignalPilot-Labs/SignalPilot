"""Semantic model endpoints (HEX inline schema editing)."""

from __future__ import annotations

import logging

from fastapi import HTTPException

from gateway.api.deps import (
    StoreD,
    get_or_fetch_schema,
    require_connection,
)
from gateway.api.schema._router import router
from gateway.api.schema._scoring import _levenshtein
from gateway.api.schema._semantic_store import _load_semantic_model, _save_semantic_model
from gateway.scope_guard import RequireScope

logger = logging.getLogger(__name__)


# ─── Semantic Model (HEX inline schema editing) ───────────────────────────


@router.get("/connections/{name}/semantic-model", dependencies=[RequireScope("read")])
async def get_semantic_model(name: str, store: StoreD):
    """Get the semantic model for a connection."""
    await require_connection(store, name)
    return _load_semantic_model(name)


@router.put("/connections/{name}/semantic-model", dependencies=[RequireScope("write")])
async def update_semantic_model(name: str, store: StoreD, body: dict):
    """Update the semantic model for a connection.

    Body: {
        "tables": { "public.customers": { "description": "...", "columns": { ... } } },
        "joins": [...],
        "glossary": { "revenue": "orders.total_amount", ... }
    }
    """
    await require_connection(store, name)

    model = _load_semantic_model(name)
    if "tables" in body:
        for table_key, table_data in body["tables"].items():
            if table_key not in model["tables"]:
                model["tables"][table_key] = {"description": "", "columns": {}}
            if "description" in table_data:
                model["tables"][table_key]["description"] = table_data["description"]
            if "columns" in table_data:
                if "columns" not in model["tables"][table_key]:
                    model["tables"][table_key]["columns"] = {}
                for col_name, col_data in table_data["columns"].items():
                    if col_name not in model["tables"][table_key]["columns"]:
                        model["tables"][table_key]["columns"][col_name] = {}
                    model["tables"][table_key]["columns"][col_name].update(col_data)
    if "joins" in body:
        model["joins"] = body["joins"]
    if "glossary" in body:
        model["glossary"].update(body["glossary"])

    _save_semantic_model(name, model)
    return model


@router.post("/connections/{name}/semantic-model/generate", dependencies=[RequireScope("write")])
async def generate_semantic_model(name: str, store: StoreD):
    """Auto-generate a semantic model skeleton from the database schema."""
    info = await require_connection(store, name)
    cached = await get_or_fetch_schema(store, name, info)

    model = _load_semantic_model(name)

    tables_added = 0
    joins_added = 0
    glossary_added = 0

    for key, table in cached.items():
        if key not in model["tables"]:
            model["tables"][key] = {"description": "", "columns": {}}
        table_model = model["tables"][key]

        if not table_model.get("description") and table.get("description"):
            table_model["description"] = table["description"]
            tables_added += 1

        if "columns" not in table_model:
            table_model["columns"] = {}

        for col in table.get("columns", []):
            col_name = col.get("name", "")
            if col_name and col_name not in table_model["columns"]:
                table_model["columns"][col_name] = {}
            if col_name and not table_model["columns"].get(col_name, {}).get("description"):
                comment = col.get("comment", "")
                if comment:
                    table_model["columns"][col_name]["description"] = comment

        for fk in table.get("foreign_keys", []):
            from_col = fk.get("column", "")
            to_table = fk.get("references_table", "")
            to_col = fk.get("references_column", "")
            to_schema = fk.get("references_schema", table.get("schema", ""))
            to_key = f"{to_schema}.{to_table}" if to_schema else to_table

            join_entry = {
                "from": f"{key}.{from_col}",
                "to": f"{to_key}.{to_col}",
                "type": "many_to_one",
            }
            existing = any(
                j.get("from") == join_entry["from"] and j.get("to") == join_entry["to"] for j in model.get("joins", [])
            )
            if not existing:
                model["joins"].append(join_entry)
                joins_added += 1

        for col in table.get("columns", []):
            col_name = col.get("name", "")
            natural = col_name.replace("_", " ").replace("-", " ").lower()
            if len(natural) > 3 and natural not in model.get("glossary", {}):
                model["glossary"][natural] = f"{key}.{col_name}"
                glossary_added += 1

    _save_semantic_model(name, model)

    return {
        "tables": len(model["tables"]),
        "joins": len(model.get("joins", [])),
        "glossary_terms": len(model.get("glossary", {})),
        "generated": {
            "tables_with_descriptions": tables_added,
            "joins_added": joins_added,
            "glossary_terms_added": glossary_added,
        },
    }


# ─── Column Name Correction (Spider2.0 hallucination fix) ──────────────────


@router.post("/connections/{name}/schema/correct-columns", dependencies=[RequireScope("write")])
async def correct_columns(name: str, store: StoreD, body: dict):
    """Suggest corrections for hallucinated column names.

    Body: {"table": "public.customers", "columns": ["customer_name", "email_addr"]}
    """
    table_key = body.get("table", "")
    candidate_columns = body.get("columns", [])
    threshold = body.get("threshold", 0.5)

    if not table_key or not candidate_columns:
        raise HTTPException(status_code=422, detail="table and columns are required")
    if len(candidate_columns) > 100:
        raise HTTPException(status_code=422, detail="columns list must have at most 100 items")

    info = await require_connection(store, name)
    cached = await get_or_fetch_schema(store, name, info)

    table_info = cached.get(table_key)
    if not table_info:
        best_table = None
        best_dist = 999
        for k in cached:
            d = _levenshtein(table_key.lower(), k.lower())
            if d < best_dist:
                best_dist = d
                best_table = k
        if best_table and best_dist <= len(table_key) * threshold:
            table_info = cached[best_table]
        else:
            return {"corrections": {}, "table_suggestion": best_table if best_table else None}

    actual_columns = {col["name"].lower(): col["name"] for col in table_info.get("columns", [])}
    corrections: dict = {}

    for candidate in candidate_columns:
        candidate_lower = candidate.lower()
        if candidate_lower in actual_columns:
            continue

        best_match = None
        best_dist = 999
        for col_lower, col_name in actual_columns.items():
            d = _levenshtein(candidate_lower, col_lower)
            if d < best_dist:
                best_dist = d
                best_match = col_name

        max_dist = max(len(candidate), 1) * threshold
        if best_match and best_dist <= max_dist:
            corrections[candidate] = {
                "suggestion": best_match,
                "distance": best_dist,
                "confidence": round(1.0 - (best_dist / max(len(candidate), 1)), 2),
            }
        else:
            corrections[candidate] = {"suggestion": None, "distance": best_dist, "confidence": 0.0}

    return {
        "table": table_key,
        "corrections": corrections,
        "total_columns": len(actual_columns),
    }
