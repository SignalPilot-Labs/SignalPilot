---
description: "Use when debugging the frontend UI, testing visual rendering, checking for broken pages, verifying component behavior, or doing end-to-end browser testing. Uses the Playwright MCP server for headless browser automation."
---

# Frontend Debug & Browser Testing

You have access to the **Playwright MCP server** which gives you a headless Chromium browser. Use it to interact with and debug the SignalPilot frontend.

## Available URLs

- **SignalPilot Web UI**: `http://host.docker.internal:3200`
- **SignalPilot Gateway API**: `http://host.docker.internal:3300`
- **Self-Improve Monitor**: `http://host.docker.internal:3400`

## Playwright MCP Tools

All tools are prefixed with `mcp__playwright__`. Key tools:

### Navigation & Screenshots

```
mcp__playwright__browser_navigate  — Navigate to a URL
mcp__playwright__browser_take_screenshot  — Capture the page or an element
mcp__playwright__browser_snapshot  — Get accessibility tree (fast, no vision needed)
```

### Interaction

```
mcp__playwright__browser_click  — Click an element (use accessibility ref from snapshot)
mcp__playwright__browser_type  — Type text into a focused element
mcp__playwright__browser_fill  — Fill a form field (clears first)
mcp__playwright__browser_select_option  — Select dropdown option
mcp__playwright__browser_hover  — Hover over an element
mcp__playwright__browser_press_key  — Press keyboard keys
```

### Inspection

```
mcp__playwright__browser_evaluate  — Run JavaScript in the page context
mcp__playwright__browser_console_messages  — Get console log messages
mcp__playwright__browser_network_requests  — Inspect network requests/responses
```

### Tab Management

```
mcp__playwright__browser_tab_new  — Open new tab
mcp__playwright__browser_tab_select  — Switch to a tab
mcp__playwright__browser_tab_close  — Close a tab
```

## Common Workflows

### Debug a broken page

1. `browser_navigate` to the page URL
2. `browser_snapshot` to see the accessibility tree
3. `browser_console_messages` to check for JS errors
4. `browser_network_requests` to check for failed API calls
5. `browser_take_screenshot` if you need to see the visual state

### Test a form flow

1. `browser_navigate` to the form page
2. `browser_snapshot` to find form field refs
3. `browser_fill` each field
4. `browser_click` the submit button
5. Check the result with `browser_snapshot` or `browser_console_messages`

### Verify API integration

1. `browser_navigate` to the page
2. `browser_network_requests` to see what API calls are made
3. `browser_evaluate` to inspect application state (e.g., React state, localStorage)

### Check responsive design

1. Navigate to the page
2. `browser_evaluate` with `window.innerWidth` / `window.innerHeight`
3. Use `browser_evaluate` to resize: `window.resizeTo(375, 812)` for mobile

## Tips

- **Use `browser_snapshot` instead of screenshots** when possible — it returns the accessibility tree which is faster and more useful for understanding page structure
- **Use accessibility refs** from snapshots to target elements for clicks/fills — more reliable than CSS selectors
- The browser runs headless inside the Docker container — all interaction is via these tools
- If the frontend is a Next.js app, check `browser_console_messages` for hydration errors
- Network requests show both the request and response, useful for debugging API issues
