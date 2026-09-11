# SignalPilot Pulse (MCP App)

The inline activity panel that MCP hosts (Claude, ChatGPT, VS Code, Goose) render after
`run_signalpilot_agent`. One fixed-height, non-scrolling surface:
an orb that shows the run's state, the current step, the last three streamed thoughts, a strip
of tool chips, a pulse line, and a link to the full chat in SignalPilot.

It does not render the transcript. The gateway exposes only display-safe fields through
`read_signalpilot_chat_view` (no tool inputs, no results).

## Build

```bash
npm ci
npm run check      # typecheck + tests + bundle
```

`.npmrc` sets `workspaces=false` because the parent SPEcosystem folder is a stray pnpm
workspace that otherwise breaks `npm install`.

`npm run build` writes a single self-contained file to
`../signalpilot/gateway/gateway/mcp/apps/pulse.html`, which the gateway serves as
`ui://signalpilot/pulse-v1.html`. `Dockerfile.gateway` runs the same build in its first stage.

## Host contract

- Height is content-driven (`autoResize`), so the surface fixes its own height per display
  mode and never scrolls internally.
- The SignalPilot ink palette and fonts are used on every host and host theme; host style
  variables are deliberately ignored so the panel always reads as SignalPilot.
- The panel is read-only: it never opens links or sends messages. Its only controls are the
  failure "Show details" toggle and a picture-in-picture / fullscreen switch, offered only when
  the host lists that mode in `availableDisplayModes`.
- No external resources: fonts are embedded as data URIs and no CSP domains are declared.

## Host simulator

`dev/host.html` plays the host side of the MCP Apps protocol against the built bundle: it
answers `ui/initialize`, pushes the first `tool-result`, serves `read_signalpilot_chat_view`
from a scripted run (or a waiting / failed / completed / cancelled snapshot), applies
`size-changed`, and logs `open-link`, `request-display-mode` and `message`. Serve the repo
root over http (any static server) and open
`/signalpilot-mcp-app/dev/host.html?scenario=run&theme=dark&width=720`. Controls cover host
style variables (ChatGPT-like), theme, width and each capability toggle.
