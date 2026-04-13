"""
pytest configuration — auto-load .env before test collection.

This ensures SPIDER2_DBT_DIR is set before test_dbt_project_map.py resolves
its module-level SPIDER2_BASE path.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
