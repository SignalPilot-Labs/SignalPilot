"""Eval run execution: clone the eval repo, spawn one docker container per
question (claude CLI wired to this gateway's MCP with the proposed knowledge
docs overlaid), grade answers against ground truth.

Deliberately simple: sequential questions, file-based state, Docker Engine API
over the unix socket via httpx (no docker CLI, no new dependencies).

Eval-set format:
    <repo>/traps.tsv           id \t kind \t state \t gt \t [mode] \t title \t why
    <repo>/prompts/<id>.txt    the natural-language question
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx

from ..config.evals import EvalRunSettings, get_eval_run_settings

logger = logging.getLogger(__name__)


def get_data_dir() -> str:
    import os

    return os.getenv("SP_DATA_DIR", str(Path.home() / ".signalpilot"))

# Unversioned path — the daemon serves its newest supported API version.
_DOCKER_API = "http://docker"


# ─── Paths & config ───────────────────────────────────────────────────────────


def eval_root() -> Path:
    root = Path(get_data_dir()) / "eval-runs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def config_path() -> Path:
    return Path(get_data_dir()) / "eval-config.json"


def load_eval_config() -> dict:
    try:
        return json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_eval_config(cfg: dict) -> dict:
    config_path().write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


# ─── Run state (file-based) ──────────────────────────────────────────────────


def _run_dir(run_id: str) -> Path:
    return eval_root() / run_id


def _write_run(run: dict) -> None:
    (_run_dir(run["id"]) / "run.json").write_text(json.dumps(run, indent=2), encoding="utf-8")


def read_run(run_id: str) -> dict | None:
    try:
        return json.loads((_run_dir(run_id) / "run.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def list_runs(limit: int = 50) -> list[dict]:
    runs = []
    for p in eval_root().iterdir():
        if (p / "run.json").exists():
            run = read_run(p.name)
            if run:
                run.pop("questions_detail", None)
                runs.append(run)
    runs.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return runs[:limit]


def read_setup_log(run_id: str, state: str) -> str | None:
    path = _run_dir(run_id) / f"setup-{_sanitize_state(state)}.log"
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def read_transcript(run_id: str, question_id: str) -> str | None:
    safe_q = re.sub(r"[^a-zA-Z0-9_-]", "_", question_id)
    path = _run_dir(run_id) / "questions" / f"{safe_q}.log"
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


# ─── Eval set parsing ────────────────────────────────────────────────────────


@dataclass
class EvalQuestion:
    id: str
    kind: str
    gt: str
    title: str
    prompt: str
    why: str = ""
    state: str = ""
    doc: str = ""  # markdown writeup from docs/<id>.md
    checks: list = field(default_factory=list)  # [{name, value, tolerance}]
    extra: dict = field(default_factory=dict)


def _load_checks(repo_dir: Path, qid: str, gt: str) -> list[dict]:
    """Gold checks for a question.

    golds/<id>.json ({"checks":[{"name","value","tolerance"}]}) wins — it
    supports multi-value golds (mart-building evals checking row counts, table
    counts, totals...). Otherwise a numeric gt column becomes a single check.
    """
    gold_file = repo_dir / "golds" / f"{qid}.json"
    if gold_file.exists():
        try:
            raw = json.loads(gold_file.read_text(encoding="utf-8"))
            checks = []
            for c in raw.get("checks", []):
                checks.append(
                    {
                        "name": str(c.get("name", "value")),
                        "value": float(c["value"]),
                        "tolerance": float(c.get("tolerance", 0.15)),
                    }
                )
            if checks:
                return checks
        except (ValueError, KeyError, TypeError) as exc:
            logger.warning("Bad golds/%s.json: %s", qid, exc)
    try:
        return [{"name": "answer", "value": float(gt.replace(",", "").replace("$", "")), "tolerance": 0.15}]
    except (ValueError, AttributeError):
        return []


def _parse_manifest_row(line: str) -> dict | None:
    """traps.tsv: id, kind, state, gt, [mount_mode], title, why (tab-separated)."""
    f = [c.strip() for c in line.rstrip("\n").split("\t")]
    if len(f) < 4 or f[0].startswith("#") or not f[0]:
        return None
    row = {"id": f[0], "kind": f[1], "state": f[2], "gt": f[3], "title": "", "why": ""}
    rest = f[4:]
    # Optional mount-mode column: a known token in position 4 means title shifts right.
    if rest and rest[0] in ("stripped", "project", "raw"):
        rest = rest[1:]
    if rest:
        row["title"] = rest[0]
    if len(rest) > 1:
        row["why"] = rest[1]
    return row


@dataclass
class EvalSet:
    name: str
    description: str
    questions: list[EvalQuestion]
    setup: dict = field(default_factory=dict)  # {image, env_file, timeout_seconds}


def _read_rel(repo_dir: Path, rel: str) -> str:
    """Read a repo-relative file, refusing path escapes."""
    path = (repo_dir / rel).resolve()
    if not str(path).startswith(str(repo_dir.resolve())):
        raise ValueError(f"Path escapes the eval repo: {rel}")
    return path.read_text(encoding="utf-8", errors="replace")


def _load_json_manifest(repo_dir: Path, manifest_path: Path) -> EvalSet:
    """eval.json index (eval-format.md): the JSON describes, files contain."""
    try:
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise RuntimeError(f"eval.json is not valid JSON: {exc}")
    defaults = m.get("defaults", {})
    default_tol = float(defaults.get("tolerance", 0.15))
    default_state = str(defaults.get("state", "clean"))
    questions: list[EvalQuestion] = []
    for entry in m.get("questions", []):
        qid = str(entry.get("id", "")).strip()
        if not qid:
            raise RuntimeError("eval.json: every question needs an id")
        prompt_rel = entry.get("prompt", f"prompts/{qid}.txt")
        try:
            prompt = _read_rel(repo_dir, prompt_rel).strip()
        except OSError:
            raise RuntimeError(f"eval.json: question '{qid}' has no prompt file ({prompt_rel})")
        doc_rel = entry.get("doc", f"docs/{qid}.md")
        try:
            doc = _read_rel(repo_dir, doc_rel)
        except OSError:
            doc = ""
        checks = [
            {
                "name": str(c.get("name", "answer")),
                "value": float(c["value"]),
                "tolerance": float(c.get("tolerance", default_tol)),
            }
            for c in entry.get("checks", [])
        ]
        if not checks:
            checks = _load_checks(repo_dir, qid, str(entry.get("gt", "")))
        gt = str(entry.get("gt", "")) or (str(checks[0]["value"]) if checks else "")
        questions.append(
            EvalQuestion(
                id=qid,
                kind=str(entry.get("kind", "query")),
                state=str(entry.get("state", default_state)),
                gt=gt,
                title=str(entry.get("title", "")) or qid,
                why=str(entry.get("why", "")),
                prompt=prompt,
                doc=doc,
                checks=checks,
            )
        )
    return EvalSet(
        name=str(m.get("name", "")) or repo_dir.name,
        description=str(m.get("description", "")),
        questions=questions,
        setup=m.get("setup", {}) if isinstance(m.get("setup"), dict) else {},
    )


def load_eval_set(repo_dir: Path) -> EvalSet:
    """Load an eval set: eval.json index preferred, legacy traps.tsv fallback."""
    json_manifest = repo_dir / "eval.json"
    if json_manifest.exists():
        return _load_json_manifest(repo_dir, json_manifest)

    manifest = repo_dir / "traps.tsv"
    if not manifest.exists():
        # Also accept evals.tsv for non-trap eval repos
        manifest = repo_dir / "evals.tsv"
    if not manifest.exists():
        raise FileNotFoundError(f"No eval.json or traps.tsv/evals.tsv manifest found in {repo_dir}")
    questions: list[EvalQuestion] = []
    for line in manifest.read_text(encoding="utf-8", errors="replace").splitlines():
        row = _parse_manifest_row(line)
        if not row:
            continue
        prompt_file = repo_dir / "prompts" / f"{row['id']}.txt"
        if not prompt_file.exists():
            continue
        doc_file = repo_dir / "docs" / f"{row['id']}.md"
        questions.append(
            EvalQuestion(
                id=row["id"],
                kind=row["kind"],
                state=row["state"],
                gt=row["gt"],
                title=row["title"] or row["id"],
                why=row["why"],
                prompt=prompt_file.read_text(encoding="utf-8", errors="replace").strip(),
                doc=doc_file.read_text(encoding="utf-8", errors="replace") if doc_file.exists() else "",
                checks=_load_checks(repo_dir, row["id"], row["gt"]),
            )
        )
    return EvalSet(name=repo_dir.name, description="", questions=questions)


async def fetch_eval_repo(repo_url: str, dest: Path, settings: EvalRunSettings) -> Path:
    """Clone a public git repo, or use a local path under the mounted projects dir."""
    if repo_url.startswith(("http://", "https://", "git@")):
        proc = await asyncio.create_subprocess_exec(
            "git", "clone", "--depth", "1", repo_url, str(dest),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode != 0:
            raise RuntimeError(f"git clone failed: {out.decode(errors='replace')[-500:]}")
        return dest
    # Local path: must live under the read-only mounted eval projects dir.
    local = Path(repo_url).resolve()
    allowed = Path(settings.projects_dir).resolve()
    if not str(local).startswith(str(allowed)):
        raise ValueError(f"Local eval paths must be under {settings.projects_dir}")
    if not local.is_dir():
        raise FileNotFoundError(f"Eval path not found: {repo_url}")
    return local


async def get_eval_set() -> EvalSet:
    """Load the configured eval set for browsing (UI question breakdown).

    Git repos are shallow-cloned into a cache refreshed at most every 5 minutes;
    local paths are read directly.
    """
    cfg = load_eval_config()
    repo_url = cfg.get("repo_url", "")
    if not repo_url:
        raise ValueError("No eval repo configured")
    settings = get_eval_run_settings()
    if repo_url.startswith(("http://", "https://", "git@")):
        cache = eval_root() / ".repo-cache"
        marker = cache / ".sp-cache-meta"
        stale = True
        try:
            meta = json.loads(marker.read_text(encoding="utf-8"))
            stale = meta.get("url") != repo_url or time.time() - meta.get("at", 0) > 300
        except (OSError, ValueError):
            pass
        if stale:
            shutil.rmtree(cache, ignore_errors=True)
            await fetch_eval_repo(repo_url, cache, settings)
            marker.write_text(json.dumps({"url": repo_url, "at": time.time()}), encoding="utf-8")
        return load_eval_set(cache)
    repo_dir = await fetch_eval_repo(repo_url, eval_root() / ".unused", settings)
    return load_eval_set(repo_dir)


# ─── Grading ─────────────────────────────────────────────────────────────────

_NUM_RE = re.compile(r"[-+]?\$?\d[\d,]*\.?\d*\s*(?:billion|million|thousand|[bmk])?", re.IGNORECASE)
_SUFFIX = {"b": 1e9, "billion": 1e9, "m": 1e6, "million": 1e6, "k": 1e3, "thousand": 1e3}


def _extract_numbers(text: str) -> list[float]:
    nums: list[float] = []
    for m in _NUM_RE.finditer(text):
        raw = m.group(0).lower().replace("$", "").replace(",", "").strip()
        mult = 1.0
        for suffix, factor in _SUFFIX.items():
            if raw.endswith(suffix):
                raw = raw[: -len(suffix)].strip()
                mult = factor
                break
        try:
            nums.append(float(raw) * mult)
        except ValueError:
            continue
    return nums


def _check_passes(check: dict, numbers: list[float]) -> bool:
    target = check["value"]
    tol = check.get("tolerance", 0.15)
    for n in numbers:
        if target == 0:
            if abs(n) < 1e-9:
                return True
        elif abs(n - target) / abs(target) <= tol:
            return True
    return False


def grade_checks(checks: list[dict], answer: str) -> tuple[str, list[dict]]:
    """Grade the answer against gold checks.

    Returns (verdict, per-check results). Verdict:
      CORRECT  — every check found within tolerance
      PARTIAL  — some checks pass (multi-check golds, e.g. mart builds)
      OFF      — numbers present, none within tolerance
      UNKNOWN  — no numbers in the answer
      UNGRADED — question has no numeric gold
    """
    if not checks:
        return "UNGRADED", []
    numbers = _extract_numbers(answer)
    results = [
        {
            "name": c["name"],
            "value": c["value"],
            "tolerance": c.get("tolerance", 0.15),
            "passed": _check_passes(c, numbers),
        }
        for c in checks
    ]
    if not numbers:
        return "UNKNOWN", results
    passed = sum(1 for r in results if r["passed"])
    if passed == len(results):
        return "CORRECT", results
    if passed > 0:
        return "PARTIAL", results
    return "OFF", results


# ─── Docker Engine API (unix socket, no docker CLI) ──────────────────────────


def _docker_client(settings: EvalRunSettings) -> httpx.AsyncClient:
    transport = httpx.AsyncHTTPTransport(uds=settings.docker_socket)
    return httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(30.0))


# The container writes the MCP config from env (base64 — immune to any shell
# quoting), pre-approves project MCP servers (claude 2.x gates them behind an
# interactive approval otherwise), then runs one claude -p turn.
_RUNNER_SCRIPT = (
    "mkdir -p /work/.claude && cd /work && "
    'echo "$SP_MCP_JSON_B64" | base64 -d > /work/.mcp.json && '
    "printf '{\"enableAllProjectMcpServers\": true}' > /work/.claude/settings.local.json && "
    'claude -p "$SP_PROMPT" --mcp-config /work/.mcp.json --strict-mcp-config '
    '--output-format stream-json --verbose --model "$SP_MODEL" --dangerously-skip-permissions'
)


async def _run_container(
    docker: httpx.AsyncClient,
    settings: EvalRunSettings,
    *,
    prompt: str,
    model: str,
    mcp_json: str,
    labels: dict[str, str],
) -> tuple[int, str]:
    """Create/start/wait/log/remove one eval container. Returns (exit_code, logs)."""
    import base64

    env = [
        f"SP_PROMPT={prompt}",
        f"SP_MODEL={model}",
        f"SP_MCP_JSON_B64={base64.b64encode(mcp_json.encode()).decode()}",
    ]
    if settings.claude_token:
        env.append(f"CLAUDE_CODE_OAUTH_TOKEN={settings.claude_token}")
    if settings.anthropic_key:
        env.append(f"ANTHROPIC_API_KEY={settings.anthropic_key}")

    create = await docker.post(
        f"{_DOCKER_API}/containers/create",
        json={
            "Image": settings.runner_image,
            "Cmd": ["sh", "-lc", _RUNNER_SCRIPT],
            "Env": env,
            "Tty": True,  # raw (non-multiplexed) log stream
            "Labels": {"signalpilot.eval": "1", **labels},
            "HostConfig": {
                "NetworkMode": settings.docker_network,
                "Memory": 2 * 1024 * 1024 * 1024,
                "NanoCpus": 2_000_000_000,
            },
        },
    )
    if create.status_code != 201:
        raise RuntimeError(f"container create failed ({create.status_code}): {create.text[:300]}")
    cid = create.json()["Id"]

    try:
        start = await docker.post(f"{_DOCKER_API}/containers/{cid}/start")
        if start.status_code not in (204, 304):
            raise RuntimeError(f"container start failed ({start.status_code}): {start.text[:300]}")

        try:
            wait = await docker.post(
                f"{_DOCKER_API}/containers/{cid}/wait",
                timeout=httpx.Timeout(settings.timeout_seconds + 30, connect=30),
            )
            exit_code = int(wait.json().get("StatusCode", -1))
        except httpx.TimeoutException:
            await docker.post(f"{_DOCKER_API}/containers/{cid}/kill")
            exit_code = -2  # timed out

        logs = await docker.get(
            f"{_DOCKER_API}/containers/{cid}/logs",
            params={"stdout": "1", "stderr": "1"},
        )
        return exit_code, logs.content.decode("utf-8", errors="replace")
    finally:
        await docker.delete(f"{_DOCKER_API}/containers/{cid}", params={"force": "1"})


def _extract_result_text(logs: str) -> str:
    """Pull the final `result` from a claude stream-json transcript."""
    for line in reversed(logs.strip().splitlines()):
        line = line.strip().rstrip("\r")
        if line.startswith("{") and '"result"' in line:
            try:
                obj = json.loads(line)
                if obj.get("type") == "result" and isinstance(obj.get("result"), str):
                    return obj["result"]
            except ValueError:
                continue
    return logs[-3000:]  # fallback: tail of raw output


# ─── Setup-state containers ──────────────────────────────────────────────────


def _sanitize_state(state: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "-", state) or "default"


def _setup_script_for(repo_dir: Path, eval_set: EvalSet, state: str) -> str | None:
    """Repo-relative setup script for a state: explicit manifest map, then the
    states/<sanitized>/setup.(sh|py) convention."""
    explicit = (eval_set.setup.get("states") or {}).get(state)
    if explicit:
        return str(explicit)
    for candidate in (f"states/{_sanitize_state(state)}/setup.sh", f"states/{_sanitize_state(state)}/setup.py"):
        if (repo_dir / candidate).exists():
            return candidate
    return None


def _parse_env_file(repo_dir: Path, rel: str) -> list[str]:
    out: list[str] = []
    try:
        for line in _read_rel(repo_dir, rel).splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                out.append(line)
    except (OSError, ValueError):
        pass
    return out


async def _run_setup_container(
    docker: httpx.AsyncClient,
    settings: EvalRunSettings,
    *,
    eval_set: EvalSet,
    repo_dir: Path,
    repo_url: str,
    script_rel: str,
    state: str,
    run_id: str,
) -> tuple[int, str]:
    """Run one state-setup script in its own container. Returns (exit, logs).

    The eval repo lands at /repo: bind-mounted read-only for local-path repos
    (host path via SP_EVAL_PROJECTS_HOST_DIR), cloned inside the container for
    git repos. Manifest setup.mounts bind extra host dirs (external dbt trees)
    under /mnt/<name>, resolved against SP_EVAL_SETUP_HOST_ROOT.
    """
    image = eval_set.setup.get("image") or settings.runner_image
    runner_cmd = f'sh "/repo/{script_rel}" "{state}"'
    if script_rel.endswith(".py"):
        runner_cmd = f'python3 "/repo/{script_rel}" "{state}"'

    binds: list[str] = []
    if repo_url.startswith(("http://", "https://", "git@")):
        cmd = f'git clone --depth 1 "$SP_EVAL_REPO_URL" /repo && cd /repo && {runner_cmd}'
    else:
        if not settings.projects_host_dir:
            raise RuntimeError("SP_EVAL_PROJECTS_HOST_DIR is not set — required to mount local eval repos into setup containers")
        rel = str(Path(repo_url).resolve()).replace(str(Path(settings.projects_dir).resolve()), "", 1).lstrip("/\\")
        host_repo = f"{settings.projects_host_dir.rstrip('/\\')}/{rel}".replace("\\", "/")
        binds.append(f"{host_repo}:/repo:ro")
        cmd = f"cd /repo && {runner_cmd}"

    for mount in eval_set.setup.get("mounts") or []:
        entry = {"path": mount, "rw": False} if isinstance(mount, str) else dict(mount)
        rel_path = str(entry.get("path", "")).strip().strip("/\\")
        if not rel_path or ".." in rel_path:
            raise RuntimeError(f"Invalid setup mount path: {mount!r}")
        if not settings.setup_host_root:
            raise RuntimeError("SP_EVAL_SETUP_HOST_ROOT is not set — required for setup.mounts")
        host_src = f"{settings.setup_host_root.rstrip('/\\')}/{rel_path}".replace("\\", "/")
        mode = "rw" if entry.get("rw") else "ro"
        binds.append(f"{host_src}:/mnt/{Path(rel_path).name}:{mode}")

    env = _parse_env_file(repo_dir, str(eval_set.setup.get("env_file", "")))
    env += [f"SP_EVAL_STATE={state}", f"SP_EVAL_REPO_URL={repo_url}", "HOME=/tmp"]
    timeout = int(eval_set.setup.get("timeout_seconds", settings.setup_timeout_seconds))

    create = await docker.post(
        f"{_DOCKER_API}/containers/create",
        json={
            "Image": image,
            "Cmd": ["sh", "-lc", cmd],
            "Env": env,
            "Tty": True,
            "Labels": {"signalpilot.eval": "1", "signalpilot.eval.setup": state, "signalpilot.eval.run": run_id},
            "HostConfig": {
                "NetworkMode": settings.docker_network,
                "Binds": binds,
                "Memory": 4 * 1024 * 1024 * 1024,
                "NanoCpus": 4_000_000_000,
            },
        },
    )
    if create.status_code != 201:
        raise RuntimeError(f"setup container create failed ({create.status_code}): {create.text[:300]}")
    cid = create.json()["Id"]
    try:
        # Setup scripts talk to the warehouse directly (unlike question
        # containers, which go through gateway MCP) — join its network too.
        extra_net = str(eval_set.setup.get("network", "")).strip()
        if extra_net:
            net_resp = await docker.post(f"{_DOCKER_API}/networks/{extra_net}/connect", json={"Container": cid})
            if net_resp.status_code not in (200, 201):
                raise RuntimeError(
                    f"setup network '{extra_net}' attach failed ({net_resp.status_code}): {net_resp.text[:200]}"
                )
        start = await docker.post(f"{_DOCKER_API}/containers/{cid}/start")
        if start.status_code not in (204, 304):
            raise RuntimeError(f"setup container start failed ({start.status_code}): {start.text[:300]}")
        try:
            wait = await docker.post(
                f"{_DOCKER_API}/containers/{cid}/wait",
                timeout=httpx.Timeout(timeout + 30, connect=30),
            )
            exit_code = int(wait.json().get("StatusCode", -1))
        except httpx.TimeoutException:
            await docker.post(f"{_DOCKER_API}/containers/{cid}/kill")
            exit_code = -2
        logs = await docker.get(f"{_DOCKER_API}/containers/{cid}/logs", params={"stdout": "1", "stderr": "1"})
        return exit_code, logs.content.decode("utf-8", errors="replace")
    finally:
        await docker.delete(f"{_DOCKER_API}/containers/{cid}", params={"force": "1"})


# ─── Run orchestration ───────────────────────────────────────────────────────


def create_run(*, doc_ids: list[str], doc_titles: list[str], question_ids: list[str] | None) -> dict:
    run_id = f"run-{datetime.now(UTC):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
    cfg = load_eval_config()
    run = {
        "id": run_id,
        "status": "preparing",
        "created_at": datetime.now(UTC).isoformat(),
        "doc_ids": doc_ids,
        "doc_titles": doc_titles,
        "question_ids": question_ids,
        "repo_url": cfg.get("repo_url", ""),
        "model": cfg.get("model", "sonnet"),
        "summary": {},
        "questions": [],
        "error": None,
    }
    _run_dir(run_id).mkdir(parents=True, exist_ok=True)
    (_run_dir(run_id) / "questions").mkdir(exist_ok=True)
    _write_run(run)
    return run


async def execute_run(
    run_id: str,
    api_key: str | None = None,
    api_key_id: str | None = None,
    org_id: str | None = None,
) -> None:
    """Background task: fetch eval set, run each question in docker, grade."""
    try:
        await _execute_run_inner(run_id, api_key)
    finally:
        if api_key_id and org_id:
            await _revoke_run_key(api_key_id, org_id)


async def _revoke_run_key(key_id: str, org_id: str) -> None:
    """Delete the per-run MCP API key minted by start_eval_run."""
    try:
        from ..db.engine import get_session_factory
        from ..store import Store

        factory = get_session_factory()
        async with factory() as session:
            store = Store(session, org_id=org_id)
            await store.delete_api_key(key_id)
            await session.commit()
    except Exception:
        logger.exception("Failed to revoke eval run API key %s", key_id)


async def _execute_run_inner(run_id: str, api_key: str | None = None) -> None:
    settings = get_eval_run_settings()
    run = read_run(run_id)
    if run is None:
        return
    cfg = load_eval_config()

    def fail(msg: str) -> None:
        run["status"] = "failed"
        run["error"] = msg
        _write_run(run)
        logger.error("Eval run %s failed: %s", run_id, msg)

    try:
        repo_dir = await fetch_eval_repo(cfg.get("repo_url", ""), _run_dir(run_id) / "repo", settings)
        eval_set = load_eval_set(repo_dir)
        questions = eval_set.questions
    except Exception as exc:
        fail(str(exc))
        return

    if run.get("question_ids"):
        wanted = set(run["question_ids"])
        questions = [q for q in questions if q.id in wanted]
    max_q = int(cfg.get("max_questions", 0) or 0)
    if max_q > 0:
        questions = questions[:max_q]
    if not questions:
        fail("No questions matched (check the manifest and prompts/ directory)")
        return

    # Group questions by state (first-appearance order) so each state's setup
    # script runs once per run, not once per question.
    state_order: list[str] = []
    for q in questions:
        if q.state not in state_order:
            state_order.append(q.state)
    questions.sort(key=lambda q: state_order.index(q.state))

    headers: dict[str, str] = {"X-SP-Eval-Docs": ",".join(run["doc_ids"])}
    if api_key:
        headers["X-API-Key"] = api_key
    mcp_json = json.dumps(
        {"mcpServers": {"signalpilot": {"type": "http", "url": settings.mcp_url, "headers": headers}}}
    )
    preamble = cfg.get("prompt_preamble", "").strip()

    run["status"] = "running"
    run["questions"] = [
        {
            "id": q.id,
            "title": q.title,
            "gt": q.gt,
            "kind": q.kind,
            "checks": q.checks,
            "status": "pending",
            "verdict": None,
            "check_results": [],
        }
        for q in questions
    ]
    run["setup"] = []
    _write_run(run)

    async with _docker_client(settings) as docker:
        current_state: str | None = None
        state_ok = True
        for i, q in enumerate(questions):
            if q.state != current_state:
                current_state = q.state
                state_ok = True
                script = _setup_script_for(repo_dir, eval_set, q.state)
                if script:
                    setup_entry = {
                        "state": q.state,
                        "script": script,
                        "status": "running",
                        "exit_code": None,
                        "duration_s": None,
                    }
                    run["setup"].append(setup_entry)
                    _write_run(run)
                    t0 = time.monotonic()
                    try:
                        exit_code, slogs = await _run_setup_container(
                            docker,
                            settings,
                            eval_set=eval_set,
                            repo_dir=repo_dir,
                            repo_url=cfg.get("repo_url", ""),
                            script_rel=script,
                            state=q.state,
                            run_id=run_id,
                        )
                        (_run_dir(run_id) / f"setup-{_sanitize_state(q.state)}.log").write_text(
                            slogs, encoding="utf-8"
                        )
                        setup_entry.update(
                            exit_code=exit_code,
                            duration_s=round(time.monotonic() - t0, 1),
                            status="ok" if exit_code == 0 else "failed",
                        )
                    except Exception as exc:
                        logger.exception("Eval run %s setup for state %s errored", run_id, q.state)
                        setup_entry.update(status="failed", error=str(exc)[:300], duration_s=round(time.monotonic() - t0, 1))
                    state_ok = setup_entry["status"] == "ok"
                    _write_run(run)

            entry = run["questions"][i]
            if not state_ok:
                entry.update(
                    status="done",
                    verdict="SETUP_FAILED",
                    answer=f"State setup for '{q.state}' failed — see the setup log.",
                )
                _write_run(run)
                continue
            entry["status"] = "running"
            _write_run(run)
            started = time.monotonic()
            try:
                prompt = f"{preamble}\n\n{q.prompt}" if preamble else q.prompt
                exit_code, logs = await _run_container(
                    docker,
                    settings,
                    prompt=prompt,
                    model=run["model"],
                    mcp_json=mcp_json,
                    labels={"signalpilot.eval.run": run_id, "signalpilot.eval.question": q.id},
                )
                answer = _extract_result_text(logs)
                if exit_code != 0 and not answer.strip():
                    verdict, check_results = "ERROR", []
                else:
                    verdict, check_results = grade_checks(q.checks, answer)
                safe_q = re.sub(r"[^a-zA-Z0-9_-]", "_", q.id)
                (_run_dir(run_id) / "questions" / f"{safe_q}.log").write_text(
                    logs, encoding="utf-8"
                )
                (_run_dir(run_id) / "questions" / f"{safe_q}.json").write_text(
                    json.dumps(
                        {
                            "id": q.id,
                            "title": q.title,
                            "prompt": q.prompt,
                            "gt": q.gt,
                            "checks": q.checks,
                            "check_results": check_results,
                            "answer": answer,
                            "verdict": verdict,
                            "exit_code": exit_code,
                            "duration_s": round(time.monotonic() - started, 1),
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                entry.update(
                    status="done",
                    verdict=verdict,
                    check_results=check_results,
                    answer=answer[:2000],
                    duration_s=round(time.monotonic() - started, 1),
                )
            except Exception as exc:
                logger.exception("Eval run %s question %s errored", run_id, q.id)
                entry.update(status="done", verdict="ERROR", answer=str(exc)[:500])
            _write_run(run)

    verdicts = [e.get("verdict") for e in run["questions"]]
    run["summary"] = {
        "total": len(verdicts),
        "correct": verdicts.count("CORRECT"),
        "partial": verdicts.count("PARTIAL"),
        "off": verdicts.count("OFF"),
        "unknown": verdicts.count("UNKNOWN"),
        "ungraded": verdicts.count("UNGRADED"),
        "error": verdicts.count("ERROR"),
        "setup_failed": verdicts.count("SETUP_FAILED"),
    }
    run["status"] = "completed"
    _write_run(run)
    # Cloned repos can be big — clean up.
    shutil.rmtree(_run_dir(run_id) / "repo", ignore_errors=True)
