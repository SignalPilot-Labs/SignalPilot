"""In-process semantic model store and filesystem helpers."""

from __future__ import annotations

import json

from gateway.store._constants import DATA_DIR

_semantic_models: dict[str, dict] = {}  # connection_name -> model


def _semantic_model_path(name: str):
    """Path to the semantic model JSON file for a connection."""
    return DATA_DIR / f"semantic_{name}.json"


def _load_semantic_model(name: str) -> dict:
    """Load semantic model from disk (cached in memory)."""
    if name in _semantic_models:
        return _semantic_models[name]
    path = _semantic_model_path(name)
    if path.exists():
        try:
            model = json.loads(path.read_text())
            _semantic_models[name] = model
            return model
        except Exception:
            pass
    empty: dict = {"tables": {}, "joins": [], "glossary": {}}
    _semantic_models[name] = empty
    return empty


def _save_semantic_model(name: str, model: dict) -> None:
    _semantic_models[name] = model
    path = _semantic_model_path(name)
    path.write_text(json.dumps(model, indent=2))
