# Security Audit — Branch `autofyn/run-a-security-a-880618` vs `main`

Date: 2026-07-29
Scope: all files added or modified on the current branch relative to `main`
(~272 files, ~19.8k insertions, ~14.6k deletions).

The audit was split into three parallel passes. Each pass produced its own
detailed report; this document is the index and executive summary.

## Reports

| File | Focus |
|------|-------|
| [`secrets-and-private-docs.md`](./secrets-and-private-docs.md) | Credential/API-key leaks in the diff, glance at `main`, and private/internal markdown that shouldn't ship in a public OSS repo. |
| [`backend-audit.md`](./backend-audit.md) | Python / FastAPI gateway, sandbox, connectors, Docker/compose, scripts. Injection, authz, SSRF, uploads, sandbox escape, GitHub webhook. |
| [`frontend-audit.md`](./frontend-audit.md) | Next.js / React notebook UI, embed code, plugin. XSS, postMessage, CSP, secrets in bundle, dependency changes. |

## Combined severity tally

| Severity | Secrets/Docs | Backend | Frontend | Total |
|----------|-------------:|--------:|---------:|------:|
| CRITICAL |            2 |       0 |        0 |     2 |
| HIGH     |            8 |       2 |        0 |    10 |
| MEDIUM   |            3 |       4 |        2 |     9 |
| LOW      |            1 |       3 |        4 |     8 |
| INFO     |            0 |       5 |        3 |     8 |

## Top priorities before public release

Read the linked reports for full context, excerpts, file/line references, and
recommended fixes. Highlights, ranked:

1. **CRITICAL — Private writeups.** `writeups/HUMAN-TASKS.md` and
   `writeups/research-metric-sources-and-connectors.md` contain internal
   roadmap, unshipped-feature specs, a private repo path
   (`kiwi0401/sp-pipelineproof-test`), customer/warehouse names (AKASA, NALA,
   `perf_nala_pg`), acknowledged security holes still open in the code,
   partnership economics with Xata, licensing/legal strategy, and internal
   stakeholder names. These must not ship to a public OSS repo.
   See `secrets-and-private-docs.md` §Private Docs.

2. **HIGH — 11 more `writeups/*.md`** with similar (but less severe) internal
   content: sprint summary, feature-1..7 writeups, UX overhaul plan, KB test
   suite plan, and `signalpilot/web/UX.md`. Recommend moving `writeups/` to a
   private repo and adding it to `.gitignore`.

3. **HIGH — Unauthenticated `POST /save-api-key`** in the notebook server
   (`signalpilot/notebook-server/signalpilot/_server/api/endpoints/agent.py`
   :115-160) accepts a secret from the request body, mutates `os.environ`
   process-wide, and has no auth. See `backend-audit.md`.

4. **HIGH — Eval runner → host-root RCE.** `gateway/evals/runner.py:553`
   selects a Docker image from an admin-supplied eval-set manifest while
   `docker-compose.yml:105` mounts `/var/run/docker.sock` into the gateway
   container. An admin who can point `repo_url` at a hostile repo can escape
   to host root. See `backend-audit.md`.

5. **MEDIUM cluster (backend).** GitHub-webhook local-mode signature-check
   fallback (`api/github_bot.py:44-48`); `git clone` of admin-supplied
   `repo_url` with shell-quoted `script_rel`/`state`
   (`evals/runner.py:287, 553-560`); legacy upload spool sizing
   (`api/uploads.py:318-338`); Notion `verification_token` short-circuit
   bypassing auth. See `backend-audit.md`.

6. **MEDIUM (frontend).** Next.js was downgraded (`^16.2.11` → `^16.2.9`),
   along with `sharp` and `brace-expansion`. Confirm no security patches were
   reverted. A new client-side Anthropic API-key input in
   `agent-chat-panel.tsx` keeps the key in React state after save. See
   `frontend-audit.md`.

7. **LOW (frontend).** CSP still allows `unsafe-inline` / `unsafe-eval`;
   `base-uri` should be `'self'`; `vscode-bindings.ts` uses `postMessage("*",
   ...)` (unchanged, but flagged for hardening). See `frontend-audit.md`.

## What is NOT a finding

- **No live secrets in the diff.** Every hit resolved to a placeholder, an
  AWS-documented example (`AKIAIOSFODNN7EXAMPLE`), a test fake
  (`sk-ant-...XYZ9`, `xoxb-test`), or an env-var reference (`${XATA_KEY:-}`).
- **No live secrets in `main`** either. One low-severity note: the same
  AWS-documented example appears in `tests/test_iam_auth.py` — not a real key.
- **No exploitable frontend XSS.** HTML rendering paths use DOMPurify with a
  strict allowlist, `react-markdown` is used without `rehype-raw`, and the KB
  document view emits React children with a `^https?://` URL allowlist.
- **PostMessage refactor introduces no new sinks.** Existing
  `postMessage("*", ...)` in `vscode-bindings.ts` is pre-existing and
  unchanged.

## Hardening recommendations (not code changes)

Even though no live secrets leaked in the diff, the writeups themselves
document the *purpose* of several tokens
(`XATA_KEY`, `SP_GITHUB_BOT_TOKEN`, `SP_GITHUB_WEBHOOK_SECRET`,
`CLAUDE_CODE_OAUTH_TOKEN`). If any of those tokens ever ended up in the
reflog on a personal machine, rotation is cheap insurance. Also flagged:
MinIO dev defaults in `docker-compose.yml` are fine for local dev but should
carry a comment warning against production use.

---

*Per the user's request, no code was changed. Fix work will be done by the
user directly.*
