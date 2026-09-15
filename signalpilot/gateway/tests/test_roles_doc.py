"""docs/docs/product/roles.mdx is generated from gateway.auth.permissions and must not drift."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from gateway.auth import PERMISSIONS

REPO_ROOT = Path(__file__).resolve().parents[3]
GENERATOR = REPO_ROOT / "docs" / "scripts" / "gen-roles.py"
DOC = REPO_ROOT / "docs" / "docs" / "product" / "roles.mdx"
SIDEBAR = REPO_ROOT / "docs" / "sidebars.ts"

pytestmark = pytest.mark.skipif(not GENERATOR.exists(), reason="docs/ is not part of this checkout")


def _generator():
    spec = importlib.util.spec_from_file_location("gen_roles", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_doc_matches_the_generator_output():
    rendered = _generator().render()
    committed = DOC.read_text(encoding="utf-8")
    assert committed == rendered, "docs/docs/product/roles.mdx is stale: run `python docs/scripts/gen-roles.py`"


def test_doc_lists_exactly_the_permission_vocabulary():
    documented = set(re.findall(r"^\| `([a-z_.:]+)` \|", DOC.read_text(encoding="utf-8"), flags=re.MULTILINE))
    assert documented == set(PERMISSIONS)


def test_doc_is_in_the_sidebar():
    assert "'product/roles'" in SIDEBAR.read_text(encoding="utf-8")
