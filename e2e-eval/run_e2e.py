"""Exercise the production evaluation harness on Docker Desktop.

The test uses the isolated ``spevalprod`` Compose stack. It verifies parallel
task execution, connection restrictions, grading, artifact storage, warehouse
isolation, regression notifications, resource cleanup, and export content.

Run this file from ``signalpilot/gateway`` after you start the stack. The test
writes evidence files to ``writeups/eval-prod-evidence/``.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx

GATEWAY = "http://localhost:3410"
MAILPIT = "http://localhost:8125"
REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE = [
    "docker",
    "compose",
    "-p",
    "spevalprod",
    "--env-file",
    str(REPO_ROOT / ".env.evalprod"),
    "-f",
    str(REPO_ROOT / "docker-compose.yml"),
    "-f",
    str(REPO_ROOT / "docker-compose.evalprod.yml"),
]
EVIDENCE = REPO_ROOT / "writeups" / "eval-prod-evidence"

PASS = []
FAIL = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append((name, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail and not ok else ""))


def _conn_list(payload) -> list[dict]:
    if isinstance(payload, list):
        return payload
    return payload.get("connections", [])


def sh(args: list[str], **kw) -> str:
    res = subprocess.run(args, capture_output=True, text=True, timeout=120, **kw)
    if res.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {res.stderr[-500:]}")
    return res.stdout


def db_sql(sql: str, database: str = "postgres") -> str:
    return sh(
        [
            *COMPOSE,
            "exec",
            "-T",
            "eval-db",
            "psql",
            "-U",
            "signalpilot",
            "-d",
            database,
            "-Atc",
            sql,
        ]
    )


def seed_parent_warehouse() -> None:
    dbs = db_sql("SELECT datname FROM pg_database WHERE datname = 'evalwh'")
    if "evalwh" in dbs:
        db_sql("DROP DATABASE evalwh WITH (FORCE)")
    db_sql("CREATE DATABASE evalwh")
    # Eval task roles must not inherit PostgreSQL's default PUBLIC CONNECT.
    # The compose role is a superuser and remains able to administer these
    # databases after the revocation.
    for database in ("postgres", "evalwh"):
        db_sql(f'REVOKE CONNECT ON DATABASE "{database}" FROM PUBLIC')
    ddl = (
        "CREATE SCHEMA raw; CREATE SCHEMA marts;"
        "CREATE TABLE raw.orders(order_id int PRIMARY KEY, amount numeric NOT NULL);"
        "INSERT INTO raw.orders SELECT g, 50 FROM generate_series(1, 100) g;"
        "CREATE TABLE marts.fct_orders AS SELECT order_id, amount FROM raw.orders;"
    )
    db_sql(ddl, database="evalwh")
    total = db_sql("SELECT sum(amount) FROM marts.fct_orders", database="evalwh").strip()
    assert total == "5000", f"seed produced sum {total!r}"
    print(f"seeded evalwh: 100 orders, total {total}")


def build_project_repo() -> None:
    """Create a minimal dbt project repository for each run."""
    proj = REPO_ROOT / "e2e-eval" / "project-repo"
    if (proj / ".git").exists():
        return
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "PROJECT_MARKER.txt").write_text("7777\n")
    (proj / "dbt_project.yml").write_text("name: e2e_proj\nversion: '1.0'\n")
    models = proj / "models" / "marts"
    models.mkdir(parents=True, exist_ok=True)
    (models / "fct_orders.sql").write_text("select * from {{ source('raw','orders') }}\n")
    for args in (
        ["init", "-q"],
        ["add", "-A"],
        ["-c", "user.email=e2e@test", "-c", "user.name=e2e", "commit", "-q", "-m", "e2e project"],
    ):
        sh(["git", "-C", str(proj), *args])


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    build_project_repo()
    api_key = sh([*COMPOSE, "exec", "-T", "gateway", "cat", "/shared/local_api_key"]).strip()
    client = httpx.Client(base_url=GATEWAY, headers={"Authorization": f"Bearer {api_key}"}, timeout=60)

    for _ in range(60):
        try:
            if client.get("/health").status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(2)
    else:
        print("gateway never became healthy")
        return 1

    admin_dsn = sh([*COMPOSE, "exec", "-T", "gateway", "printenv", "SP_EVAL_PG_ADMIN_DSN"]).strip()
    warehouse_password = urlsplit(admin_dsn).password
    assert warehouse_password, "SP_EVAL_PG_ADMIN_DSN must contain a password"
    warehouse_dsn = "postgresql" + f"://signalpilot:{quote(warehouse_password, safe='')}@eval-db:5432/evalwh"

    seed_parent_warehouse()

    # Pin the read tasks to the shared build branch.
    existing = client.get("/api/connections").json()
    names = [c["name"] for c in _conn_list(existing)]
    connection_payload = {
        "db_type": "postgres",
        "connection_string": warehouse_dsn,
    }
    if "evalwh_conn" in names:
        r = client.put("/api/connections/evalwh_conn", json=connection_payload)
    else:
        r = client.post("/api/connections", json={"name": "evalwh_conn", **connection_payload})
    check("upsert evalwh_conn", r.status_code in (200, 201), r.text[:300])

    r = client.put(
        "/api/evals/config",
        json={
            "repo_url": "/eval-projects/eval-set",
            "model": "sonnet",
            "max_tasks": 0,
            "prompt_preamble": "",
            "connection": "evalwh_conn",
            "autorun_on_knowledge_add": False,
            "notify_emails": ["owner@e2e.test"],
        },
    )
    check("save eval config", r.status_code == 200, r.text[:300])

    # Create a second warehouse that the evaluated agent cannot access.
    # This warehouse verifies the stored connection restriction.
    if "decoy_conn" in names:
        r = client.put("/api/connections/decoy_conn", json=connection_payload)
    else:
        r = client.post("/api/connections", json={"name": "decoy_conn", **connection_payload})
    check("upsert decoy_conn", r.status_code in (200, 201), r.text[:300])

    r = client.get("/api/evals/tasks")
    check("manifest v2 loads", r.status_code == 200, r.text[:300])
    tasks = r.json().get("tasks", [])
    check("6 tasks parsed", len(tasks) == 6, f"got {len(tasks)}")
    check(
        "classes routed",
        {t["id"]: t["class"] for t in tasks}.get("w1_rebuild_fct_orders") == "write",
    )

    # Run the complete evaluation set.
    r = client.post("/api/evals/runs", json={"doc_ids": [], "task_ids": None})
    check("run starts", r.status_code == 201, r.text[:300])
    run_id = r.json()["id"]
    print(f"run 1: {run_id}")

    max_active = 0
    progress_samples = []
    for _ in range(180):
        p = client.get(f"/api/evals/runs/{run_id}/progress").json()
        max_active = max(max_active, len(p.get("active", [])))
        progress_samples.append(p)
        if p.get("status") in ("completed", "failed"):
            break
        time.sleep(2)
    (EVIDENCE / "e2e-progress-samples.json").write_text(json.dumps(progress_samples[-20:], indent=2))

    run = client.get(f"/api/evals/runs/{run_id}").json()
    (EVIDENCE / "e2e-run1.json").write_text(json.dumps(run, indent=2))
    check("run completed", run.get("status") == "completed", str(run.get("error")))
    check("parallel execution observed", max_active >= 2, f"max concurrent active={max_active}")

    verdicts = {t["id"]: t["verdict"] for t in run.get("tasks", [])}
    print(f"verdicts: {verdicts}")
    check("r1 CORRECT via MCP pin", verdicts.get("r1_sum_via_mcp") == "CORRECT", str(verdicts))
    check("r2 wrong answer caught", verdicts.get("r2_wrong_answer") == "OFF", str(verdicts))
    check(
        "dbt project tarball shipped (no credential in pod)",
        verdicts.get("r3_project_tarball") == "CORRECT",
        str(verdicts),
    )

    # Verify that header removal does not bypass the stored connection restriction.
    r = client.get(f"/api/evals/runs/{run_id}/tasks/r4_pin_evasion/transcript")
    evasion = r.text if r.status_code == 200 else ""
    (EVIDENCE / "e2e-pin-evasion-transcript.txt").write_text(evasion, encoding="utf-8")
    # The agent asked for decoy_conn with every header stripped; the only
    # acceptable outcome is a refusal naming the pinned connection.
    result_line = evasion.strip().splitlines()[-1] if evasion.strip() else ""
    check(
        "header-stripped MCP call is still pinned",
        "is not available in this eval run" in result_line,
        result_line[-300:],
    )
    check(
        "decoy warehouse rows never returned",
        "leaked" not in result_line,
        result_line[-300:],
    )
    check(
        "connection enumeration hides everything but the pin",
        "decoy_conn (" not in result_line and "evalwh_conn" in result_line,
        result_line[-300:],
    )

    # Verify that each evaluation credential expires with the run.
    keys = client.get("/api/keys").json()
    key_names = [k.get("name", "") for k in (keys if isinstance(keys, list) else keys.get("keys", []))]
    check(
        "no eval keys left behind",
        not any(n.startswith(f"eval-{run_id}") for n in key_names),
        str([n for n in key_names if n.startswith("eval-")]),
    )
    check("w1 rebuild graded CORRECT", verdicts.get("w1_rebuild_fct_orders") == "CORRECT", str(verdicts))
    check("w2 skipped rebuild caught", verdicts.get("w2_rebuild_skipped") == "OFF", str(verdicts))

    w1 = next((t for t in run.get("tasks", []) if t["id"] == "w1_rebuild_fct_orders"), {})
    check(
        "w1 ran on its own branch", bool((w1.get("branch_name") or "").startswith("eval-")), str(w1.get("branch_name"))
    )
    cap = w1.get("capture_result") or {}
    fp = ((cap.get("tables") or {}).get("marts.fct_orders") or {}).get("fingerprint") or {}
    check("capture fingerprint took", fp.get("row_count") == 100, json.dumps(fp)[:200])
    check("capture grain unique", (fp.get("grain") or {}).get("unique") is True, json.dumps(fp.get("grain"))[:200])

    # Verify the recorded build fingerprint and repository references.
    check("build fingerprint recorded", str(run.get("build_fingerprint", "")).startswith("fp-"))
    check("eval set ref recorded", bool(run.get("eval_set_ref")))

    # Verify observed coverage and the project model count.
    coverage = run.get("coverage") or {}
    check(
        "observed coverage from audit",
        "fct_orders" in (coverage.get("observed") or []),
        json.dumps(coverage)[:300],
    )
    check("project ref recorded", bool(run.get("project_ref")), str(run.get("project_ref")))
    check(
        "coverage pct over project models",
        coverage.get("models_total") == 1 and coverage.get("pct") == 100.0,
        json.dumps({k: coverage.get(k) for k in ("models_total", "pct", "marts_pct")}),
    )

    # Verify the transcript, setup log, and artifact in S3.
    r = client.get(f"/api/evals/runs/{run_id}/tasks/r1_sum_via_mcp/transcript")
    check("transcript served from S3", r.status_code == 200 and "result" in r.text, r.text[:200])
    r = client.get(f"/api/evals/runs/{run_id}/tasks/w1_rebuild_fct_orders/setup/setup/log")
    check("setup log served from S3", r.status_code == 200 and "dropped" in r.text, r.text[:200])
    r = client.get(f"/api/evals/runs/{run_id}/artifacts")
    artifacts = r.json().get("artifacts", [])
    check("capture artifact in MinIO", any("duckdb" in a["path"] for a in artifacts), str(artifacts))

    # Verify that teardown removes evaluation databases and connections.
    leftover = db_sql("SELECT datname FROM pg_database WHERE datname LIKE 'eval-%'").strip()
    check("branches deleted after tasks", leftover == "", leftover)
    conns = client.get("/api/connections").json()
    conn_names = [c["name"] for c in _conn_list(conns)]
    check("per-task connections deleted", not any(n.startswith("eval-") for n in conn_names), str(conn_names))

    # Verify that write tasks do not modify the parent warehouse.
    parent_rows = db_sql("SELECT count(*) FROM marts.fct_orders", database="evalwh").strip()
    check("parent warehouse untouched", parent_rows == "100", parent_rows)

    # Verify that each write task receives a branch-scoped database role.
    # Teardown must remove the role.
    roles = db_sql("SELECT rolname FROM pg_roles WHERE rolname LIKE 'eval-%'").strip()
    check("per-branch roles dropped with their branch", roles == "", roles)
    setup_log = client.get(f"/api/evals/runs/{run_id}/tasks/w1_rebuild_fct_orders/setup/setup/log").text
    check(
        "task DSN is not the admin credential",
        f"signalpilot:{warehouse_password}" not in setup_log,
        setup_log[-200:],
    )

    # Run only the task that returns an incorrect answer.
    r = client.post("/api/evals/runs", json={"doc_ids": [], "task_ids": ["r2_wrong_answer"]})
    check("run 2 starts", r.status_code == 201, r.text[:300])
    run2_id = r.json()["id"]
    for _ in range(90):
        p = client.get(f"/api/evals/runs/{run2_id}/progress").json()
        if p.get("status") in ("completed", "failed"):
            break
        time.sleep(2)
    run2 = client.get(f"/api/evals/runs/{run2_id}").json()
    (EVIDENCE / "e2e-run2.json").write_text(json.dumps(run2, indent=2))
    check("run 2 completed", run2.get("status") == "completed", str(run2.get("error")))

    acc = client.get("/api/evals/accuracy").json()
    (EVIDENCE / "e2e-accuracy.json").write_text(json.dumps(acc, indent=2))
    history = acc.get("history", [])
    check("accuracy history has both runs", len(history) >= 2, f"{len(history)} rows")
    regs = acc.get("regressions", [])
    check("regression recorded", any(g["run_id"] == run2_id for g in regs), json.dumps(regs)[:300])

    try:
        msgs = httpx.get(f"{MAILPIT}/api/v1/messages", timeout=10).json()
        subjects = [m.get("Subject", "") for m in msgs.get("messages", [])]
        check("regression email in mailpit", any("accuracy dropped" in s for s in subjects), str(subjects))
    except Exception as exc:
        check("regression email in mailpit", False, str(exc))

    # Verify that the build fingerprint rejects a mismatched warehouse.
    r = client.put(
        "/api/evals/config",
        json={
            "repo_url": "/eval-projects/eval-set-badfp",
            "model": "sonnet",
            "max_tasks": 0,
            "prompt_preamble": "",
            "connection": "evalwh_conn",
            "autorun_on_knowledge_add": False,
            "notify_emails": [],
        },
    )
    r = client.post("/api/evals/runs", json={"doc_ids": []})
    if r.status_code == 201:
        badfp_id = r.json()["id"]
        for _ in range(60):
            p = client.get(f"/api/evals/runs/{badfp_id}").json()
            if p.get("status") in ("completed", "failed"):
                break
            time.sleep(2)
        check(
            "fingerprint gate refuses mismatched warehouse",
            p.get("status") == "failed" and "fingerprint" in (p.get("error") or ""),
            str(p.get("error"))[:300],
        )
    else:
        check("fingerprint gate refuses mismatched warehouse", False, r.text[:200])
    # Restore the valid evaluation set.
    client.put(
        "/api/evals/config",
        json={
            "repo_url": "/eval-projects/eval-set",
            "model": "sonnet",
            "max_tasks": 0,
            "prompt_preamble": "",
            "connection": "evalwh_conn",
            "autorun_on_knowledge_add": False,
            "notify_emails": ["owner@e2e.test"],
        },
    )

    # Verify that the reaper removes an orphaned evaluation branch.
    db_sql('CREATE DATABASE "eval-zzzzz1-orphan"')
    swept = False
    for _ in range(90):  # The reaper interval is 120 seconds.
        left = db_sql("SELECT datname FROM pg_database WHERE datname = 'eval-zzzzz1-orphan'").strip()
        if not left:
            swept = True
            break
        time.sleep(3)
    check("reaper sweeps orphaned branches", swept)

    # Export the run artifacts.
    r = client.get(f"/api/evals/runs/{run_id}/export")
    check("export zip downloads", r.status_code == 200, r.text[:200])
    if r.status_code == 200:
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        names = zf.namelist()
        (EVIDENCE / "e2e-export-listing.txt").write_text("\n".join(names))
        check("export has run.json", "run.json" in names, str(names))
        check("export has transcripts", any(n.startswith("transcripts/") for n in names), str(names))
        check("export has artifacts", any(n.startswith("artifacts/") for n in names), str(names))
        (EVIDENCE / f"{run_id}-export.zip").write_bytes(r.content)

    print(f"\n{'=' * 60}\n{len(PASS)} passed, {len(FAIL)} failed")
    for name, detail in FAIL:
        print(f"  FAIL {name}: {detail}")
    (EVIDENCE / "e2e-results.json").write_text(
        json.dumps({"passed": [p[0] for p in PASS], "failed": [{"name": f[0], "detail": f[1]} for f in FAIL]}, indent=2)
    )
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
