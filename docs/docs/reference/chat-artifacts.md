---
title: Chat artifact MCP tools
---

Use `list_artifacts` to discover saved files from a SignalPilot chat:

```json
{"thread_id": "<chat-id>"}
```

Each artifact includes `artifact_id`, `filename`, `path`, `kind`, `mime_type`,
`byte_size`, `sha256`, and `origin_run_id`. The list is the current chat file
manifest, not a historical snapshot of a particular run. It includes files
retained from earlier turns. Legacy published chart/table snapshots are not
part of this file manifest.

Use `download_artifacts` with selected IDs:

```json
{"thread_id": "<chat-id>", "artifact_ids": ["<file-id-1>", "<file-id-2>"]}
```

The response provides a separate `download_url` and `expires_at` for each file.
Links expire after **two minutes** and can be redeemed **once**. The URL uses
`SP_PUBLIC_GATEWAY_URL`, never S3. The gateway returns the file bytes directly
without redirecting to storage. Both text and structured tool responses include
the artifact metadata and redemption instructions.

In a browser, open the link and click Download. For agent HTTP tools, split
`download_url` at `#`. POST to the URL before `#` with `Content-Type:
application/json` and body `{"token":"<fragment after #>"}`. Save the response
bytes as the returned filename. A plain GET returns only the download page.
The MCP server cannot write onto the caller's computer.

Tokens contain 256 random bits. Only SHA-256 token hashes are stored in the
database. Redemption atomically deletes the grant before reading the file,
so concurrent requests cannot reuse it. Expired, consumed, unknown, and
revoked links receive the same generic rejection. Failed or interrupted
downloads also consume the grant; request another through the authenticated
MCP tool. Range/resume requests are not supported.

The token is a URL fragment, not a query parameter or path segment, so browsers
do not send it in access-log URLs. The page removes the fragment from its
history entry, has no external scripts or analytics, uses a restrictive CSP,
and sends `no-store` and `no-referrer` headers. Do not enable request-body
capture on `/api/artifact-download` or log MCP download results in external
APM/proxy systems. The POST body necessarily contains the token.

These remain bearer links: anyone who steals one can redeem it first. Do not
publish or log them. Expiry does not revoke copies already downloaded.
Export bytes remain private in the chat storage prefix; token expiry is not
file deletion. Expired grants are pruned when issuing new grants.

Batches accept 1 to 20 distinct IDs and at most 100 MiB total. Downloads pin
hash-verified bytes to an export snapshot and use attachment headers. If a
file changes during preparation, list the artifacts again and retry.

Both tools require `agent:run` scope and enforce chat ownership, runtime
environment, and connection-scoped credentials. Artifact IDs are not storage
paths. Unknown or inactive files are rejected.

Finished `get_signalpilot_agent`, `wait_signalpilot_agent`, and
`get_signalpilot_agent_event` responses include `artifacts` without download
URLs. `get_signalpilot_agent_context` also includes the current manifest.
These responses label it `artifact_scope: "current_chat_manifest"` so callers
do not confuse the current files with a historical run's output.
