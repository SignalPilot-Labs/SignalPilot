# Backend Security Audit

Scope: `git diff main..HEAD` restricted to Python files and Docker/YAML on
branch `autofyn/run-a-security-a-880618`. Credential-scanning is handled by a
sibling reviewer and is excluded here.

## Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 0     |
| HIGH     | 2     |
| MEDIUM   | 4     |
| LOW      | 3     |
| INFO     | 5     |

Overall posture is defensible. The new attack surface is well-scoped:
identifiers are validated before being interpolated into SQL, the /demo route
never persists the shared org key, connection pinning stops it from being
misused, and CSRF/CORS is on in cloud mode with an explicit allow-list. The
findings below are concentrated around (a) admin-scope features that
delegate execution to attacker-controlled inputs (eval runner + repo_url,
setup manifest picking Docker image), (b) an unauthenticated notebook-server
endpoint that mutates process-wide env and forwards a key to the gateway on
behalf of the caller, and (c) local-mode fallbacks in webhook receivers that
open a door if the gateway is ever exposed unprotected.

---

## Findings

### [HIGH] Notebook-server `/save-api-key` has no auth check and mutates process env

- File: `signalpilot/notebook-server/signalpilot/_server/api/endpoints/agent.py:115-160`
- Category: authz / secrets
- Description: `save_api_key` accepts an arbitrary `api_key` from the request
  body, forwards it to the gateway `PUT /api/user/secrets` using the
  server-side `gateway_headers()` (i.e. the notebook server's own gateway
  credentials — not the caller's), and unconditionally sets
  `os.environ["ANTHROPIC_API_KEY"] = api_key`. There is no session check on
  this router, and the fallback path (line ~155) does the `os.environ` write
  even when the gateway call fails. Setting `os.environ` mutates
  process-global state that every kernel / subsequent request in the same
  notebook-server process inherits.
- Impact: A caller who can reach the notebook server (e.g. via the notebook
  proxy path) can (1) overwrite the current user's gateway-stored Anthropic
  key (or write one for a user who had none), and (2) poison the
  notebook-server process's `ANTHROPIC_API_KEY` env for every subsequent
  request routed to that pod — a form of stored key confusion across kernel
  sessions in the same worker.
- Recommendation: Require an authenticated notebook session on this route
  (use the same session-cookie / SP session dep the other agent endpoints
  rely on). Do not mutate `os.environ` at request time; store the key on the
  session/kernel scope instead. Reject the request entirely if the gateway
  call fails rather than silently "local_only".
- Confidence: high

### [HIGH] Eval-set manifest chooses the Docker image executed on the gateway host

- File: `signalpilot/gateway/gateway/evals/runner.py:553` (`_run_setup_container`),
  compose reference: `docker-compose.yml:105` (`/var/run/docker.sock:/var/run/docker.sock`)
- Category: sandbox escape / RCE-via-config
- Description: The gateway mounts the host Docker socket. The eval runner
  invokes containers based on the eval-set manifest fetched by
  `fetch_eval_repo(repo_url, …)`. Line 553:
  `image = eval_set.setup.get("image") or settings.runner_image` — the
  image name is taken straight from the manifest. `_run_setup_container`
  also feeds `cmd` (from `runner_cmd`) into `sh -lc`, and honors
  `eval_set.setup.get("mounts")` for bind mounts under
  `SP_EVAL_SETUP_HOST_ROOT`. `repo_url` is set through the admin
  `PUT /api/evals/config` endpoint, and once set, the manifest inside that
  repo is fully attacker-controlled.
- Impact: An admin (or anyone who reaches the admin scope, e.g. via a stolen
  admin key) can point `repo_url` at a repo whose `manifest` names an
  arbitrary image and arbitrary bind mounts under `SP_EVAL_SETUP_HOST_ROOT`.
  Combined with the mounted docker socket, this is effectively RCE-as-root
  on the gateway host (container escape via docker.sock is trivial: run a
  container with `--privileged` / mount `/`).
- Recommendation: Do not let the manifest choose the image — restrict to a
  server-side allow-list (or force `settings.runner_image` / a small set of
  known images). Reject bind-mount entries that resolve outside a fixed
  read-only path even before the `..` check. Reconsider mounting
  `/var/run/docker.sock` into the same container that runs application HTTP
  logic; a dedicated docker-runner sidecar with a narrower socket proxy
  (e.g. `docker-socket-proxy`) is the standard pattern.
- Confidence: high

### [MEDIUM] Eval-config `repo_url` cloned via `git clone` with attacker-controlled URL

- File: `signalpilot/gateway/gateway/evals/runner.py:287-306` (`fetch_eval_repo`),
  and repeated at line 560 inside the setup container script.
- Category: injection (git remote / SSRF-adjacent)
- Description: `fetch_eval_repo` does
  `git clone --depth 1 <repo_url> <dest>` when the URL starts with
  `http://`, `https://`, or `git@`. There's a leading-`-` argument-splitting
  guard (via the prefix check), but the URL itself is otherwise unfiltered.
  While CVE-2017-1000117-class `ssh://…-oProxyCommand=…` is largely mitigated
  in modern git, this still lets an admin-scoped caller pull arbitrary code
  onto the gateway host (and later the setup container script does
  `git clone --depth 1 "$SP_EVAL_REPO_URL" /repo && … {runner_cmd}` where
  `runner_cmd` is built from manifest-controlled `script_rel` and `state`
  values interpolated into a double-quoted shell string — shell-quote
  breakout is possible with a `"` in `script_rel`).
- Impact: With admin scope: repo-driven code arriving on the gateway host,
  and shell-quote breakout inside the setup container (further amplified by
  the previous finding).
- Recommendation: Validate `repo_url` against an allow-list of hosts (or
  only accept https URLs to a known-good host set). Do not interpolate
  `script_rel`/`state` into a shell command; instead pass them as
  positional args (`sh /repo/script.sh state`) via `Cmd: ["sh", "/repo/…", state]`.
  Reject any `script_rel` containing shell metacharacters or `..`.
- Confidence: medium

### [MEDIUM] GitHub webhook accepts unsigned events in non-cloud mode

- File: `signalpilot/gateway/gateway/api/github_bot.py:44-48`
- Category: auth (webhook trust)
- Description: If `SP_GITHUB_WEBHOOK_SECRET` is unset and the process is
  *not* in cloud mode, `github_webhook` accepts any body without an HMAC
  signature check (only `is_cloud_mode()` triggers the 503). In cloud mode
  the behavior is correct. If a self-hosted / on-prem gateway is ever
  exposed to the internet without setting the secret, any caller can
  trigger arbitrary PR scans against configured connections.
- Impact: Data exfil / DoS potential: the scan runs warehouse queries
  (`COUNT(*)`, `information_schema` reads, per-column null aggregates) and
  the bot's GitHub token posts a comment + status. In cloud-mode
  deployments this is fine; the risk lives at the "self-hoster exposes
  local mode" boundary.
- Recommendation: Require the webhook secret unconditionally (or only
  accept the webhook from `127.0.0.1` / an internal network when the secret
  is unset). Log a startup warning when the receiver is enabled without a
  secret.
- Confidence: medium

### [MEDIUM] Legacy `/api/evals/upload` skips the multipart flow's size preflight

- File: `signalpilot/gateway/gateway/api/uploads.py:318-338`
- Category: DoS / resource
- Description: The legacy single-POST upload path (kept for small files /
  older clients) writes the whole body to a spool before size is checked
  (`file.file.seek(0, 2)`), then rejects at `cfg.max_bytes`. The body-size
  middleware is configured for the `/api/evals/upload` prefix with
  `_eval_uploads_settings().max_bytes + 1_048_576` — i.e. up to
  ~500 MB (default max_mb=500 in compose) is buffered into the spool and
  streamed onto disk before the endpoint gets to enforce the cap. This
  applies to the multipart routes too, but they only carry small JSON.
- Impact: A single POST can burn up to the large per-path limit worth of
  disk/tmpfs even when the size will be rejected. With a naive attacker
  script this is a cheap disk-exhaustion primitive.
- Recommendation: Reject early in the endpoint using the `Content-Length`
  header before letting FastAPI consume the body (or lower the legacy
  endpoint's per-path body cap and route it through a small-file endpoint
  distinct from the multipart prefix).
- Confidence: medium

### [MEDIUM] `/api/notion/webhooks/events` returns 200 to any body containing `verification_token`

- File: `signalpilot/gateway/gateway/api/notion.py:612-614`
- Category: hardening / logging DoS
- Description: The verification-token branch is checked *before* signature
  verification, and returns 200 unconditionally with a WARNING log line. An
  unauthenticated caller can send `{"verification_token": "..."}` to
  generate warnings and 200 replies indefinitely.
- Impact: Log flooding and observability noise. Not exploitable for data.
- Recommendation: Once the integration has completed subscription
  verification, ignore or 401 further verification-token payloads that
  don't match a stored value; or rate-limit this path.
- Confidence: high

### [LOW] `schema_watch` PR body includes truncated markdown built from server-fetched schemas

- File: `signalpilot/gateway/gateway/schema_watch/runner.py:212-225`
- Category: injection (into GitHub PR)
- Description: The PR body embeds table/column names from the target
  warehouse verbatim in markdown. If those names contain markdown/HTML
  fragments, they end up in a GitHub PR body — cosmetic, but on issues
  triggered by an org's own warehouse it can render as an image / link
  chosen by the DB owner. Not exploitable across orgs; the watch is
  org-scoped.
- Recommendation: Escape backticks / pipes in table/column names when
  rendering markdown (`f"`{name.replace('`','\'')}`"`).
- Confidence: low

### [LOW] `github_repo` pattern permits `..` in either segment

- File: `signalpilot/gateway/gateway/api/github_bot.py:94` and
  `signalpilot/gateway/gateway/api/schema_watches.py:24`
- Category: input validation
- Description: `pattern=r"^[\w.-]+/[\w.-]+$"` accepts values like
  `foo/../bar` (the two segments are already split by `/`, so the
  attacker can put `..` in either half). GitHub's API rejects those as
  404, but the value is also interpolated into git branch names and file
  paths in `schema_watch.runner.report_drift_pr`. `connection_name` in
  those file paths is safe (constrained by the connection's own
  `[a-zA-Z0-9_-]` pattern), but the repo half only affects the outgoing
  GitHub URL. Practical exposure is low.
- Recommendation: Tighten the pattern to disallow `..` per-segment and
  `.` / `-` at segment boundaries.
- Confidence: medium

### [LOW] MCP failed-auth rate limiter keys by rightmost `X-Forwarded-For`

- File: `signalpilot/gateway/gateway/auth/mcp_api_key.py:324-341, 268-269`
- Category: rate limiting
- Description: `_extract_client_ip` uses the rightmost XFF value, which is
  the correct anti-spoof choice only when the request went through exactly
  the trusted proxy set that appends. When the gateway is behind a single
  trusted reverse proxy this is correct; behind multiple untrusted hops or
  no proxy, the rightmost IP is the last hop and every failed attempt
  shares a bucket. Notes call this out already.
- Recommendation: Make the trust depth configurable
  (`SP_TRUSTED_PROXY_DEPTH`) and skip that many rightmost hops when the
  headers are trusted; otherwise fall back to `scope["client"][0]`.
- Confidence: medium

### [INFO] Eval runner mints a `read,write`-scoped API key and passes it into an
attacker-controlled container

- File: `signalpilot/gateway/gateway/api/eval_runs.py:113-118`,
  `signalpilot/gateway/gateway/evals/runner.py:724-729`
- Category: least privilege
- Description: The runner mints an API key with `["read", "write"]`
  scopes and injects it into the eval container via `X-API-Key`. The
  container executes `claude -p` with `--dangerously-skip-permissions` on
  an admin-configured repo. Key is revoked after the run
  (`_revoke_run_key`), which is the important control. Impact is bounded
  by scope: no `admin`, so no ability to mint keys, edit connections,
  etc. Still worth calling out because scope alone is what stops the
  eval box from mutating knowledge docs and other write-scope surfaces.
- Recommendation: Introduce a narrower scope (e.g. `read`-only, or
  `eval_read`) for the eval-runner MCP token; write-scope surfaces used
  by the eval flow can be re-checked or restricted to only knowledge
  overlays via `X-SP-Eval-Docs`.
- Confidence: medium

### [INFO] Gateway container mounts `/var/run/docker.sock`

- File: `docker-compose.yml:105`
- Category: blast radius
- Description: The gateway container has direct Docker daemon access. This
  is required for the eval-runner + eval-setup flows but means any RCE
  reaching the gateway process (see the HIGH finding above) is trivially
  a host root escape.
- Recommendation: Route Docker calls through
  `tecnativa/docker-socket-proxy` (or similar) with only the container
  endpoints the eval runner uses whitelisted (`GET /containers/json`,
  `POST /containers/create` scoped to a fixed image allow-list,
  `POST /containers/{id}/start|kill|logs`, `DELETE /containers/{id}`).
- Confidence: high

### [INFO] `_run_setup_container` `image` from manifest + `env_file` parsing

- File: `signalpilot/gateway/gateway/evals/runner.py:553, 580`
- Category: least privilege
- Description: `_parse_env_file(repo_dir, eval_set.setup.get("env_file", ""))`
  reads an env file from the repo checkout — attacker-controlled contents
  become container env vars, which is fine on its own but pairs with the
  attacker-chosen `image` to allow arbitrary code selection.
- Recommendation: See the HIGH finding — restricting the image is the
  primary control here.
- Confidence: medium

### [INFO] `github_bot.client.GitHubBotClient` accepts `token` verbatim

- File: `signalpilot/gateway/gateway/github_bot/client.py:35-46`
- Category: hardening
- Description: The token is placed in `Authorization: token <token>` on
  every subsequent request. `resolve_bot_token` looks up an
  installation-scoped token first, falling back to a PAT
  (`SP_GITHUB_BOT_TOKEN`) if the DB lookup raises. That fallback is
  logged as a warning — good — but it swaps identity silently. A
  transient DB error during a `synchronize` event would make the shared
  PAT scan a repo linked to a different customer.
- Recommendation: Do not fall back to the PAT when the installation
  lookup errors; fail the scan (webhook already returns 503 on lookup
  failure, so keep that behavior consistent inside `run_pr_scan`).
- Confidence: medium

### [INFO] `notion.webhook_router` receiver processes any `comment.created` payload after signature check

- File: `signalpilot/gateway/gateway/api/notion.py:666+`
- Category: informational
- Description: The signature check is enforced; from there on the code
  writes to `gateway_notion_webhook_deliveries`. Signature checking uses
  the shared secret — the audit did not surface a bypass. This entry is
  a "reviewed clean" marker.
- Confidence: high

---

## Areas reviewed clean

- **Semantic-layer providers** (`gateway/semantic_layer/providers.py`) —
  all identifiers pass through `_check_ident` / `_check_qualified` before
  being interpolated into SQL; string-literal interpolation (`WHERE
  table_catalog = '{parts[0]}'`) is safe because the same regex validator
  runs first (`_IDENT_RE = ^[A-Za-z_][A-Za-z0-9_$]*$`).
- **PipelineProof scanner SQL construction**
  (`gateway/github_bot/scanner.py`) — model names come from
  `parse_changed_models` which filters via `_MODEL_RE`; schema/table
  values used with f-string interpolation into `information_schema`
  queries originate from that regex-validated split. `_qid` /
  `_qname` quoting is applied to identifiers used in the final aggregate
  query.
- **Redshift `SET search_path`** — schema list comes from `pg_namespace`,
  each name double-quote escaped before joining.
- **Knowledge search** (`store/knowledge_search.py`) — all filters use
  named binds (`:org_id`, `:q`, etc.) via `text()` + parameter dict.
- **GitHub webhook HMAC verification** — SHA-256, `hmac.compare_digest`,
  and prefix stripping.
- **Xata credential indirection** (`connectors/xata_creds.py`) — the
  demo flow correctly stores only `xata_credential_ref="demo"`, resolves
  the org key from env at use time, and `enforce_xata_scope` pins
  project + branch; the pinned-connection edit-guard in
  `connections/crud.py` blocks moving these fields.
- **Eval upload multipart flow** — S3 keys are server-generated, key
  shape is re-validated on `complete` / `abort`, size is enforced twice
  (initiate on declared size, complete on `head_object` after upload),
  and the notification email is plain-text.
- **CSRF middleware** — cookie-only mutation requests are gated on
  `Sec-Fetch-Site` / `Origin` / `Referer` against an explicit allow-list;
  webhook prefixes are exempted with a documented reason.
- **CORS allow-list construction** — cloud mode filters non-HTTPS
  origins out and falls back to hardcoded prod origins if
  `SP_ALLOWED_ORIGINS` is empty.
- **Body size middleware** — pure ASGI, early rejects on
  `Content-Length`, wraps `receive` for chunked bodies, tracks
  `response.start` to avoid ASGI protocol violations on late rejects.
- **New DB models** (`db/models.py`) — `GatewayKnowledgeRetrieval` and
  `GatewaySchemaWatch` both carry `org_id NOT NULL` and have indexes /
  unique constraints scoped by `org_id`.
- **Dbt error parsing** (`gateway/dbt/error_parse.py`) — pure regex, no
  code execution paths.
- **Slack OAuth redirect** (`api/slack.py`) — `_safe_redirect_url` +
  `_is_safe_redirect_target` allow-list, so open-redirect is blocked.
- **`schema_watch/runner.py` PR creation** — deterministic branch names,
  base64-encoded file contents, `github_repo` and `connection_name`
  patterns limit path traversal into the `PUT contents` API.
- **Sandbox delete IDOR** (`api/sandboxes.py`) — `get_sandbox(id, org_id)`
  scoping applied before delete/kill.
