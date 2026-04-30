# `git clone` invoked with user-controlled URL and branch (no `--` separator) — argument injection

**Status:** DEPRIORITIZED — feature disabled in cloud as of 2026-04-30; owner not actively maintaining. Severity rating retained to reflect technical risk; treat as low-priority until the feature is re-enabled.

- Slug: git-clone-arg-injection-via-project-import
- Severity: High
- Cloud impact: Partial (gateway code path is reachable in cloud; the cloud-mode log at `main.py:87` only logs that "dbt projects disabled" — `POST /api/projects` source=github is NOT actually gated, see Affected surface)
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/project_store.py:374-390`, `signalpilot/gateway/gateway/api/projects.py:24-31`

Back to [issues.md](issues.md)

---

## Problem

`ProjectStore._clone_and_wire` calls `subprocess.run` to invoke `git clone` with three values that originate from the request body (`git_url`, `branch`, `project_dir`):

```python
# project_store.py:374-390
def _clone_and_wire(
    self, git_url: str, branch: str, project_dir: Path, project_name: str, connection: ConnectionInfo
) -> None:
    import subprocess
    result = subprocess.run(
        ["git", "clone", "--branch", branch, "--depth", "1", git_url, str(project_dir)],
        capture_output=True,
        text=True,
        timeout=120,
    )
```

Three issues:

1. **No `--` end-of-options separator.** Even though `subprocess.run` uses an argv list (so shell injection is not directly possible), `git` itself parses positional arguments looking for option-like tokens. If `git_url` starts with `-` (e.g. `--upload-pack=...` style), git interprets it as an option. With a `git_url` of `--upload-pack=/tmp/payload.sh` and a benign-looking second positional, git can be coerced into running an attacker-supplied command via the `--upload-pack` knob (CVE-2017-1000117 family). Adding `--` before user input is the canonical defense.
2. **`branch` is also user-controlled.** `git clone --branch <branch> ...` accepts arbitrary refspec; but more importantly, branch values containing `..` or shell metacharacters land in the cloned working tree's HEAD ref and are quoted into hooks paths in some downstream uses (`dbt parse` runs inside the clone).
3. **`project_dir` derives from `proj.name`** via `_managed_dir`, which builds a path under `DATA_DIR/projects/{name}`. `proj.name` is bounded by Pydantic constraints, but `_managed_dir` is not shown to enforce traversal blocking — see `_create_new_project`'s use of `proj.name` in YAML templates.

The route `POST /api/projects` (`api/projects.py:24-31`) calls `store.create_project(proj)` which dispatches to `_create_github`/`_create_dbt_cloud`/`_create_local` solely on `proj.source`, with `RequireScope("write")` as the only gating. The "cloud-mode disables dbt projects" claim is only a startup log message; the route remains registered and reachable in cloud builds.

---

## Impact

- An authenticated attacker (any user with `write` scope, which is the default scope on a fresh API key) can pass a crafted `git_url` and trigger argument injection against the gateway's `git` binary.
- Historical `git` upload-pack argument injection has resulted in arbitrary command execution in the gateway container. Modern git versions are hardened against the most direct form, but the lack of a `--` separator leaves the surface available for any future regression.
- Even without RCE, the lack of validation on `git_url` allows SSRF via `git://internal-host/repo` or `https://169.254.169.254/...` style URLs that git will dutifully fetch from.

---

## Exploit scenario

1. Attacker has an API key with `write` scope (default for any non-read-only key).
2. Attacker calls `POST /api/projects`:

```json
{
  "name": "innocent",
  "source": "github",
  "connection_name": "any-existing-conn",
  "git_url": "https://169.254.169.254/latest/meta-data/iam/security-credentials/",
  "git_branch": "main"
}
```

3. The gateway's `git clone` SSRFs to AWS instance metadata; if the gateway pod has IMDSv1 reachable, credentials are returned.
4. Alternative payloads target internal services (`http://kubernetes.default.svc/...`).

---

## Affected surface

- Files: `signalpilot/gateway/gateway/project_store.py:374-390`, `signalpilot/gateway/gateway/api/projects.py:24-31`
- Endpoints: `POST /api/projects` with `source: "github"` or `source: "dbt-cloud"`
- Auth modes: any authenticated principal with `write` scope (cloud + local).

---

## Proposed fix

In `project_store._clone_and_wire`:

- Validate `git_url` with `urlparse`; reject schemes other than `https` and `ssh`. Reject hostnames matching the SSRF block list shared with `network_validation.py`.
- Validate `branch` against `^[A-Za-z0-9._/\-]{1,200}$`.
- Add `--` before user-controlled positionals: `["git", "clone", "--branch", branch, "--depth", "1", "--", git_url, str(project_dir)]`.
- Run with `env={"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/bin/true"}` so authentication failures don't hang.
- Gate behind `is_cloud_mode()` returning False if dbt projects truly are disabled in cloud — match the startup log to actual route registration.

Also add a unit test that asserts argv contains `"--"` immediately before `git_url`, and a test that rejects `git_url` starting with `-`.

---

## Verification / test plan

- Unit: `tests/test_project_store_security.py::test_clone_argv_includes_double_dash`.
- Unit: `tests/test_projects.py::test_post_project_rejects_dash_prefixed_git_url`.
- Manual: `curl -X POST .../api/projects` with `git_url="--upload-pack=/usr/bin/id"` and verify HTTP 400 and no subprocess invocation.
- Fixed when: `git_url` validated at boundary, `--` present in argv, cloud-mode gate matches log message.

---

## Rollout / migration notes

- Pure additive validation; existing callers using legitimate `https://github.com/...` URLs are unaffected.
- Communicate URL constraints to existing customers using github-import projects.
- Rollback: revert validation; not destructive.
