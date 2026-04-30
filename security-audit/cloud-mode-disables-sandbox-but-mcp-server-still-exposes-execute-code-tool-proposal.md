# `main.py` logs "sandbox disabled in cloud" but MCP server tool registry still includes `execute_code`

**Status:** DEPRIORITIZED — feature disabled in cloud as of 2026-04-30; owner not actively maintaining. Severity rating retained to reflect technical risk; treat as low-priority until the feature is re-enabled.

- Slug: cloud-mode-disables-sandbox-but-mcp-server-still-exposes-execute-code-tool
- Severity: Medium
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/mcp_server.py:307-326`, `signalpilot/gateway/gateway/main.py:87`

Back to [issues.md](issues.md)

---

## Problem

`main.py:87` logs that sandbox and code execution are disabled in cloud mode:

```python
# main.py:87
if is_cloud_mode():
    logger.info("STARTUP: Cloud mode — sandbox, file browser, dbt projects disabled")
```

However, the MCP `execute_code` tool is unconditionally registered in the tool registry. It performs an early return in cloud mode:

```python
# mcp_server.py:307-326
@mcp.tool()
async def execute_code(code: str, timeout: int = 30) -> str:
    ...
    # Cloud mode gate
    from .deployment import is_cloud_mode
    if is_cloud_mode():
        return "Error: Code execution is not available in cloud mode"
    ...
```

Problems:
1. **Tool is advertised but non-functional.** Claude Code and any MCP client calls `tools/list` and sees `execute_code` in the response. The tool appears available, leading users and AI agents to call it, receiving a confusing error message instead of a proper "not supported" indication.
2. **Attack surface advertising.** Advertising `execute_code` as a tool in cloud mode signals to an attacker that code execution was considered and may be re-enabled. An attacker may probe for configuration errors that bypass the cloud guard.
3. **The cloud guard is a string return, not an exception.** MCP tools return strings, but returning "Error: Code execution is not available" is indistinguishable from a runtime error. A proper implementation would not register the tool at all, or return an MCP `isError: true` response.
4. **Sandbox manager may still be reachable.** If the Kubernetes deployment of the sandbox is still running (e.g., for other purposes), and the `SP_SANDBOX_MANAGER_URL` env var is set, the sandbox manager is reachable from the gateway pod even though the tool "disables" it at the application layer.

---

## Impact

- AI agents (Claude Code) see `execute_code` in the tool list and attempt to use it in cloud mode → confusing error messages in agent workflows.
- The sandbox manager URL is still configured and reachable, meaning a developer who removes the cloud guard accidentally re-enables sandbox access.
- Tool discovery reveals the gateway's capabilities to an attacker, including disabled features.

---

## Exploit scenario

1. Developer adds a feature flag to re-enable sandbox for an enterprise customer.
2. They comment out the `if is_cloud_mode(): return` check.
3. `execute_code` now runs in cloud mode — but the tool was already registered, so no additional code change is needed.
4. If the sandbox manager is not running (as expected), calls fail with a network error. But if the sandbox manager is accidentally left running or reachable via internal network, code executes against it.

**Information disclosure:**
```bash
curl -X POST https://gateway.signalpilot.ai/mcp \
  -H "X-API-Key: sp_valid_key" \
  -d '{"jsonrpc":"2.0","method":"tools/list"}'
# Response includes "execute_code" — attacker knows code execution was considered
```

---

## Affected surface

- Files: `signalpilot/gateway/gateway/mcp_server.py:307-326`, `signalpilot/gateway/gateway/main.py:87`
- Endpoints: MCP `tools/list`, `tools/call execute_code`
- Auth modes: Cloud mode (tool registered but gated)

---

## Proposed fix

Conditionally register `execute_code` only when sandbox is enabled:

```python
# mcp_server.py — conditional tool registration:
from .deployment import is_cloud_mode

if not is_cloud_mode():
    @mcp.tool()
    async def execute_code(code: str, timeout: int = 30) -> str:
        """Execute Python code in an isolated gVisor sandbox."""
        # Cloud mode check is no longer needed — not registered in cloud
        if not code or not code.strip():
            return "Error: Code cannot be empty."
        ...

    @mcp.tool()
    async def sandbox_status() -> str:
        """Check the health of the sandbox manager."""
        ...
```

Alternatively, use a feature flag:

```python
# config.py or settings:
SANDBOX_ENABLED = os.environ.get("SP_SANDBOX_ENABLED", "false" if is_cloud_mode() else "true").lower() == "true"

# mcp_server.py:
if SANDBOX_ENABLED:
    @mcp.tool()
    async def execute_code(...): ...
```

This allows enterprise deployments to re-enable sandbox via `SP_SANDBOX_ENABLED=true` without code changes.

---

## Verification / test plan

**Unit tests:**
1. `test_execute_code_not_in_tool_list_cloud_mode` — cloud mode, call `tools/list`, assert `execute_code` not in response.
2. `test_execute_code_in_tool_list_local_mode` — local mode, call `tools/list`, assert `execute_code` present.
3. `test_execute_code_works_local_mode` — local mode with sandbox running, assert successful execution.

**Manual checklist:**
- Deploy gateway in cloud mode (`SP_DEPLOYMENT_MODE=cloud`).
- Call `POST /mcp` with `{"method":"tools/list"}`.
- Before fix: `execute_code` appears in list. After fix: not listed.

---

## Rollout / migration notes

- Conditional tool registration requires care — FastMCP may not support conditional `@mcp.tool()` decorators depending on the library version. Use a factory pattern or conditional registration at server startup.
- Check if FastMCP allows dynamic tool deregistration: `mcp.remove_tool("execute_code")` in the cloud mode startup path.
- Customer-visible impact: `execute_code` disappears from the Claude Code plugin's tool list in cloud mode. AI agents that tried to use it will no longer see it as an option.
- Rollback: revert to unconditional `@mcp.tool()` registration.
