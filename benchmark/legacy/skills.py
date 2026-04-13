"""
Skills system — load and manage benchmark skills from project DB.

Skills are prompt fragments or strategies that augment the agent's
SQL generation capabilities. They can be stored as:
1. YAML/JSON files in benchmark/skills/
2. Entries in the project database (skills table)

Each skill has:
- name: unique identifier
- description: what it does
- prompt: the actual prompt fragment to inject
- category: schema_exploration | sql_generation | error_recovery | optimization
- applicable_dbs: list of DB types it applies to (empty = all)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import SKILLS_DIR


@dataclass
class Skill:
    """A benchmark skill that augments agent capabilities."""
    name: str
    description: str
    prompt: str
    category: str = "general"
    applicable_dbs: list[str] = field(default_factory=list)
    priority: int = 0  # higher = applied first

    def applies_to(self, db_type: str) -> bool:
        return not self.applicable_dbs or db_type in self.applicable_dbs


# ─── Built-in skills ─────────────────────────────────────────────────────────

BUILTIN_SKILLS: list[Skill] = [
    Skill(
        name="schema_explorer",
        description="Systematic schema exploration strategy",
        prompt=(
            "When exploring a database schema:\n"
            "1. First list all tables to understand the scope\n"
            "2. For each relevant table, examine column names and types\n"
            "3. Check for foreign key relationships between tables\n"
            "4. Sample a few rows from key tables to understand data formats\n"
            "5. Look for naming conventions (snake_case, camelCase, abbreviations)\n"
            "6. Identify potential join columns even without explicit FKs"
        ),
        category="schema_exploration",
        priority=10,
    ),
    Skill(
        name="sqlite_expert",
        description="SQLite-specific SQL patterns and gotchas",
        prompt=(
            "SQLite-specific considerations:\n"
            "- Use PRAGMA table_info(table_name) for column details\n"
            "- SQLite uses dynamic typing — check actual values, not just declared types\n"
            "- Use GROUP_CONCAT for string aggregation (not STRING_AGG)\n"
            "- LIMIT/OFFSET syntax: LIMIT n OFFSET m\n"
            "- Date functions: date(), time(), datetime(), strftime()\n"
            "- No RIGHT JOIN or FULL OUTER JOIN — use LEFT JOIN with table order swap\n"
            "- CAST(x AS REAL) for float division, not x::float\n"
            "- Use IFNULL(x, default) instead of COALESCE for two args\n"
            "- For LIKE, SQLite is case-insensitive for ASCII by default"
        ),
        category="sql_generation",
        applicable_dbs=["sqlite"],
        priority=9,
    ),
    Skill(
        name="complex_query_builder",
        description="Strategies for building complex multi-join queries",
        prompt=(
            "For complex queries requiring multiple joins:\n"
            "1. Break the question into sub-questions\n"
            "2. Write and test each sub-query independently first\n"
            "3. Use CTEs (WITH clauses) for readability and debugging\n"
            "4. Verify join conditions produce expected row counts\n"
            "5. Check for NULL handling in join columns\n"
            "6. Use DISTINCT when joins might produce duplicates\n"
            "7. Validate aggregation groups match the question's granularity"
        ),
        category="sql_generation",
        priority=8,
    ),
    Skill(
        name="error_recovery",
        description="Strategies for recovering from SQL errors",
        prompt=(
            "When a query fails or returns unexpected results:\n"
            "1. Read the error message carefully — it usually points to the exact issue\n"
            "2. Check column names exist in the table (they may be quoted or case-sensitive)\n"
            "3. Verify data types match (especially for comparisons and joins)\n"
            "4. If aggregation fails, check GROUP BY includes all non-aggregated columns\n"
            "5. If results are wrong, sample the intermediate tables to verify join logic\n"
            "6. Try simplifying the query to isolate which part produces wrong results\n"
            "7. Check if the question implies sorting or specific column ordering"
        ),
        category="error_recovery",
        priority=7,
    ),
    Skill(
        name="result_validator",
        description="Validate query results against the question",
        prompt=(
            "After getting query results, validate them:\n"
            "1. Does the number of result columns match what the question asks for?\n"
            "2. Do the result values make sense given the domain?\n"
            "3. Are numeric results in the right order of magnitude?\n"
            "4. If the question asks for a count, is the result a single number?\n"
            "5. If the question asks 'which', does the result identify specific entities?\n"
            "6. Check edge cases: empty results, NULL values, duplicate rows"
        ),
        category="validation",
        priority=6,
    ),
]


def _skill_dirs() -> list[Path]:
    """Return all directories to search for skill files (repo + SP_BENCHMARK_DIR)."""
    repo_skills = Path(__file__).resolve().parent / "skills"
    dirs = [repo_skills]
    if SKILLS_DIR != repo_skills:
        dirs.append(SKILLS_DIR)
    return dirs


def load_skills_from_files() -> list[Skill]:
    """Load skills from JSON files in both repo and SP_BENCHMARK_DIR skills dirs."""
    skills = []
    seen: set[str] = set()

    for skills_dir in _skill_dirs():
        if not skills_dir.exists():
            continue
        for path in sorted(skills_dir.glob("*.json")):
            if path.name in seen:
                continue
            seen.add(path.name)
            try:
                data = json.loads(path.read_text())
                if isinstance(data, list):
                    skills.extend(Skill(**s) for s in data)
                else:
                    skills.append(Skill(**data))
            except Exception as e:
                print(f"Warning: Failed to load skill from {path}: {e}")

    return skills


def load_skills_from_db(db_path: str | None = None) -> list[Skill]:
    """Load skills from the project database."""
    if not db_path:
        return []

    import sqlite3
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT name, description, prompt, category, applicable_dbs, priority "
            "FROM skills WHERE active = 1 ORDER BY priority DESC"
        )
        skills = []
        for row in cursor:
            skills.append(Skill(
                name=row["name"],
                description=row["description"],
                prompt=row["prompt"],
                category=row["category"] or "general",
                applicable_dbs=json.loads(row["applicable_dbs"]) if row["applicable_dbs"] else [],
                priority=row["priority"] or 0,
            ))
        conn.close()
        return skills
    except Exception as e:
        print(f"Warning: Failed to load skills from DB: {e}")
        return []


def get_skills(
    names: list[str] | None = None,
    db_type: str = "",
    include_builtin: bool = True,
    db_path: str | None = None,
) -> list[Skill]:
    """Get applicable skills, sorted by priority."""
    all_skills: list[Skill] = []

    if include_builtin:
        all_skills.extend(BUILTIN_SKILLS)

    all_skills.extend(load_skills_from_files())
    all_skills.extend(load_skills_from_db(db_path))

    # Filter by name if specified
    if names:
        all_skills = [s for s in all_skills if s.name in names]

    # Filter by DB type
    if db_type:
        all_skills = [s for s in all_skills if s.applies_to(db_type)]

    # Sort by priority (highest first)
    all_skills.sort(key=lambda s: s.priority, reverse=True)

    return all_skills


def skills_to_prompt(skills: list[Skill]) -> str:
    """Convert a list of skills into a system prompt fragment."""
    if not skills:
        return ""

    sections = []
    for skill in skills:
        sections.append(f"### {skill.name}\n{skill.prompt}")

    return "## Skills & Strategies\n\n" + "\n\n".join(sections)


def init_skills_table(db_path: str):
    """Create the skills table in the project database."""
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS skills (
            name TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            prompt TEXT NOT NULL,
            category TEXT DEFAULT 'general',
            applicable_dbs TEXT DEFAULT '[]',
            priority INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
