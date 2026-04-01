"""
Download and set up Spider2-Lite dataset for benchmarking.

Spider2-Lite repo: https://github.com/xlang-ai/Spider2
We clone the minimal files needed: JSONL task definitions, gold results,
SQLite databases, and documentation.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from .config import DATASETS_DIR, SPIDER2_DIR, SPIDER2_DATABASES_DIR, SPIDER2_JSONL


def setup_spider2(force: bool = False) -> bool:
    """Clone Spider2 repo and set up datasets. Returns True if successful."""
    if SPIDER2_DIR.exists() and not force:
        if SPIDER2_JSONL.exists():
            print(f"Spider2-Lite already set up at {SPIDER2_DIR}")
            return True
        print("Spider2 directory exists but looks incomplete. Re-downloading...")
        shutil.rmtree(SPIDER2_DIR)

    DATASETS_DIR.mkdir(parents=True, exist_ok=True)

    print("Cloning Spider2 repository (sparse checkout for spider2-lite only)...")
    repo_url = "https://github.com/xlang-ai/Spider2.git"
    temp_dir = DATASETS_DIR / "_spider2_clone"

    try:
        # Sparse clone — only spider2-lite directory
        subprocess.run(
            ["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse", repo_url, str(temp_dir)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "sparse-checkout", "set", "spider2-lite"],
            cwd=str(temp_dir),
            check=True,
            capture_output=True,
            text=True,
        )

        # Move spider2-lite to our datasets dir
        src = temp_dir / "spider2-lite"
        if src.exists():
            if SPIDER2_DIR.exists():
                shutil.rmtree(SPIDER2_DIR)
            shutil.move(str(src), str(SPIDER2_DIR))
            print(f"Spider2-Lite dataset installed at {SPIDER2_DIR}")
        else:
            print("ERROR: spider2-lite directory not found in clone")
            return False

    except subprocess.CalledProcessError as e:
        print(f"Git clone failed: {e.stderr}")
        return False
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)

    # Verify
    if not SPIDER2_JSONL.exists():
        print(f"WARNING: {SPIDER2_JSONL} not found after setup")
        return False

    # Count tasks by type
    counts = {"bigquery": 0, "snowflake": 0, "sqlite": 0, "other": 0}
    with open(SPIDER2_JSONL) as f:
        for line in f:
            task = json.loads(line.strip())
            iid = task.get("instance_id", "")
            if iid.startswith("bq"):
                counts["bigquery"] += 1
            elif iid.startswith("sf"):
                counts["snowflake"] += 1
            elif iid.startswith("local"):
                counts["sqlite"] += 1
            else:
                counts["other"] += 1

    print(f"\nSpider2-Lite tasks: {sum(counts.values())} total")
    for k, v in counts.items():
        if v > 0:
            print(f"  {k}: {v}")

    # Check SQLite databases
    if SPIDER2_DATABASES_DIR.exists():
        dbs = list(SPIDER2_DATABASES_DIR.glob("*/*.sqlite"))
        print(f"\nSQLite databases found: {len(dbs)}")
    else:
        print("\nWARNING: SQLite databases directory not found.")
        print("You may need to download them separately from the Spider2 release.")

    return True


def list_sqlite_tasks() -> list[dict]:
    """Load Spider2-Lite JSONL and return only SQLite tasks."""
    if not SPIDER2_JSONL.exists():
        raise FileNotFoundError(
            f"Spider2-Lite JSONL not found at {SPIDER2_JSONL}. "
            "Run: python -m benchmark.setup_spider2"
        )

    tasks = []
    with open(SPIDER2_JSONL) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            task = json.loads(line)
            # SQLite tasks have instance_ids starting with "local"
            if task.get("instance_id", "").startswith("local"):
                tasks.append(task)
    return tasks


def get_sqlite_db_path(db_id: str) -> Path | None:
    """Find the SQLite database file for a given db_id."""
    if not SPIDER2_DATABASES_DIR.exists():
        return None

    # Spider2 stores SQLite DBs as: sqlite/{db_id}/{db_id}.sqlite
    db_path = SPIDER2_DATABASES_DIR / db_id / f"{db_id}.sqlite"
    if db_path.exists():
        return db_path

    # Try without subdirectory
    db_path = SPIDER2_DATABASES_DIR / f"{db_id}.sqlite"
    if db_path.exists():
        return db_path

    # Search recursively
    for p in SPIDER2_DATABASES_DIR.rglob("*.sqlite"):
        if p.stem == db_id:
            return p

    return None


def get_external_knowledge(doc_filename: str) -> str:
    """Load external knowledge document content."""
    from .config import SPIDER2_DOCUMENTS_DIR

    if not doc_filename:
        return ""

    # Search in documentation directories
    search_dirs = [
        SPIDER2_DOCUMENTS_DIR,
        SPIDER2_DIR / "resource" / "documents",
        SPIDER2_DIR / "resource",
    ]

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for p in search_dir.rglob(doc_filename):
            return p.read_text(errors="replace")

    return ""


if __name__ == "__main__":
    force = "--force" in sys.argv
    success = setup_spider2(force=force)
    sys.exit(0 if success else 1)
