# Feature 8 — UX Overhaul (softer, cleaner, more "pro")

**Status:** Complete — UX document written first (`signalpilot/web/UX.md`), then
implemented section-by-section, verified with live screenshots
(`signalpilot/web/e2e-ux-*.png`), reviewed by an 8+8 agent panel (1.05M tokens),
majors fixed.

## The document → the build

Per the brief, `UX.md` was written before any code: three user loops (trust / wiring /
exploration), a grouped IA, and a design system adopted from the landing page. Then:

1. **Tokens + fonts** (`globals.css`, `layout.tsx`): CRT black `#050505` → warm ink
   `#0e0e0f`; hard `#222` borders → translucent `rgba(255,255,255,0.08)`; **DM Sans**
   as the UI font with **JetBrains Mono reserved for evidence** (SQL, metrics, ids,
   kbd) — mono = data, sans = chrome, the landing page's voice; radius scale
   10/14/16px; rounded scrollbars; `prefers-reduced-motion` honored globally.
2. **Sidebar**: flat 12-item list → grouped IA (**Activity** chats/reports/audit,
   **Data** connections/schema/query, **Workspace** projects/library/integrations),
   rounded active pill + mint dot, health warning dot on Connections, pending-review
   **NavBadge on Library** (agent proposals visible from anywhere), softened footer.
3. **PageHeader/TerminalBar** (every page inherits): sans semibold titles + pill
   subtitle chip, optional tab rows; the terminal mock lost its CRT chrome (window
   dots, marquee) but keeps the quiet mono command caption.
4. **Connections ⊃ Health**: merged as a shared tab row (Connections ↔ Health) —
   deliberately tabs instead of the doc's original redirect, preserving deep links;
   Health removed from nav; UX.md updated to match.
5. **Page sweep** — 4 parallel agents over disjoint file sets, one style contract:
   radius tokens everywhere, tracking/uppercase stripped above 11px, evidence values
   `font-mono tabular-nums`, `transition-colors duration-150`, scanline/marquee/
   glow-pulse decorations removed, grid background dimmed to a faint mint radial.
   Scoped design layers (knowledge page, evals transcript viewer) untouched by design.

## Panel outcomes — applied

- **Ctrl+C hijack** (shipping bug): the Chats nav shortcut intercepted the copy chord —
  clipboard/select-all chords are now never intercepted; misleading hint removed.
- **Unlayered mono reset**: `letter-spacing: 0` on `.font-mono` beat every Tailwind
  tracking utility app-wide → moved into `@layer base`.
- **Tooltip clipping**: new `overflow-hidden` on connection cards clipped badge/latency
  tooltips (non-portal tooltips) → removed.
- Stale nav surfaces: keyboard-shortcuts help + command palette still advertised
  `/health` and wrong chords (pre-existing double-handler conflict made worse by the
  IA change) → both aligned to the sidebar's real bindings.
- `capitalize` mis-casing acronyms ("Api Keys") → removed; lowercase voice everywhere.
- Missed surfaces swept: keyboard-shortcuts dialog, error boundary, sign-in/up,
  notebooks page, theme editor, paywall.
- Micro-label tracking normalized to the documented `0.08em` (19 files).
- Old-palette logo hex, skeleton/TerminalBar radius mismatch, UX.md truthfulness.

## Backlog (best of ideation)

1. **Needs-review dashboard strip** — pending KB proposals + open drift PRs + sick
   connections as the first thing on the dashboard ("nothing needs you" when clear). (high/medium)
2. **Agent-runs activity card** — replace raw audit rows with thread-level narrative +
   per-run verification fingerprint from chat events. (high/medium)
3. **Schema-watch client** — Feature 4's watches have an API but no UI; drift-PR card. (high/medium)
4. **Verification pass-rate hero metric** from eval runs. (medium/small)
5. **Command palette rebuilt from a shared nav source** (single source for sidebar +
   palette + shortcuts; add settings sub-pages). (high/medium)
6. **Responsive sidebar** (icon rail at md, drawer below). (medium/large)
7. Shared Button/Card CVA primitives now that styles converged; focus-visible mint
   outline pass; aria-current on tab rows; dead-CSS prune (scanline/glow-pulse
   keyframes, radius tokens unused). (mixed/small)

## Verification
- `tsc` clean for all touched files (remaining errors pre-exist in notebook embeds).
- Docker web builds; 8 pages screenshotted before/after fixes — grouped sidebar,
  soft rounded cards, sans/mono contrast, Connections↔Health tabs all confirmed.
