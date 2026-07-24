# SignalPilot Console — UX Overhaul Document

*The product-defining document for the 2026-07 UX overhaul. Describes the optimal app
flow first, then the design system, then the section-by-section implementation plan.
Styling follows the landing page (`WebstormProjects/signalpilot/landing-page`).*

---

## 1. Who uses this app, and for what

Three loops, in priority order:

1. **The trust loop (daily)** — a data lead checks *what agents did*: chats/agent runs,
   verification outcomes, audit trail, knowledge proposals awaiting review. The app's
   core value is governed confidence, so this loop must be front-and-center.
2. **The wiring loop (occasional)** — connect warehouses, link GitHub/Notion/Slack,
   configure watches and keys. Setup tasks; done rarely, must be findable, not loud.
3. **The exploration loop (weekly)** — browse schema, run governed queries, open
   notebooks, read reports. Support workflows for humans double-checking the data.

### The optimal flow
- Land on **Dashboard** = trust summary: agent activity, verification pass rates,
  pending KB reviews, connection health, recent drift PRs. Every card links into its
  section. The dashboard answers "did anything happen that needs me?" in five seconds.
- One **left sidebar**, grouped by loop (see IA below), always visible, never nested
  menus. Health status lives *inside* Connections (a sick database is a property of a
  connection, not a place). Keyboard palette (⌘K) already exists and stays.
- Approvals (pending knowledge, upcoming: PR-bot findings) surface as **badges** on
  their nav items, so "needs me" is visible from anywhere.

## 2. Information architecture

Sidebar regrouped from one flat list into four labeled groups:

| Group | Items | Notes |
|---|---|---|
| *(brand)* | Dashboard | trust summary |
| **Activity** | Chats, Reports, Audit | what agents did |
| **Data** | Connections *(absorbs Health)*, Schema, Query, Notebooks, Sandboxes | exploring + wiring the data plane |
| **Workspace** | Projects, Knowledge Base, Evals*, Integrations | building + curating; evals hidden unless enabled |
| **Settings** | Settings (keys, MCP, GitHub under it as today) | footer area |

Page moves/merges:
- **/health merges into the Connections section** — implemented as a shared tab row
  (Connections ↔ Health) rather than a redirect, preserving deep links while removing
  Health from the nav. The sidebar health dot moves onto the Connections item.
- Everything else keeps its route (bookmarks/deep links preserved); the change is
  grouping + presentation, not URL churn.

## 3. Design system (adopted from the landing page)

### Typography — the biggest single change
- **DM Sans** becomes the UI font (nav, headings, body, buttons, tables).
- **JetBrains Mono** stays for what is *evidence*: SQL, code, metrics/numbers, IDs,
  log lines, keyboard hints. Mono = data, Sans = chrome. That contrast is the
  landing page's voice and it reads instantly more professional than all-mono.
- Scale: 13px base UI, 15–16px body copy, 20–24px page titles (weight 550–650,
  tracking −0.01em). No more uppercase-tracked mono for every label — reserve
  uppercase micro-labels (11px, +0.08em) for group headers only.

### Color — soften from CRT black to warm ink
| Token | Old | New |
|---|---|---|
| `--color-bg` | #050505 | **#0e0e0f** (landing `--sp-ink`, warmer) |
| `--color-bg-card` | #0a0a0a | **#141416** (landing card-solid) |
| `--color-bg-elevated` | #0d0d0d | **#18181a** |
| `--color-bg-hover` | #111111 | **#1b1b1e** |
| `--color-border` | #222222 | **rgba(255,255,255,0.08)** (translucent, glassy) |
| `--color-border-hover` | #333333 | **rgba(255,255,255,0.16)** |
| `--color-text` | #eeeeee | **#ededed** |
| `--color-text-muted` | #999999 | **#9c9c96** (landing muted, warm) |
| `--color-text-dim` | #666666 | **#6b6b66** |
| `--color-accent` | #ffffff | #ffffff (buttons stay white-solid like landing pills) |
| `--color-success` | #00ff88 | #00ff88 (brand mint — used *sparingly*: live dots, primary CTAs, pass states) |
| `--color-sidebar` | #030303 | **#0b0b0c** |

Principles: crisp 1px translucent borders over shadows; shadows only as soft mint
glows on primary CTAs; generous radius (**10px controls, 14–16px cards, 999px pills**
— replacing the current 0–4px brutalism); background gradients only as faint radial
mint glow in page headers.

### Motion — restrained
- Keep: fade-in, stagger-fade (cap ~350ms), scale-in for dialogs.
- Soften: hover transitions 150–200ms ease; card hover = border-lighten +
  translateY(−1px), no glow-pulse.
- Remove from default surfaces: scanline, blink, data-flow marquees (terminal/CRT
  effects fight "professional"; keep the keyframes for the terminal component only).
- Honor `prefers-reduced-motion` globally.

## 4. Section-by-section plan

1. **Tokens + fonts + primitives** (`globals.css`, `layout.tsx`): new palette, DM Sans
   via next/font, radius/scrollbar softening, shared `.card`, `.btn` conventions.
   *This alone restyles ~80% of surfaces because every page consumes the tokens.*
2. **Sidebar** (`components/layout/sidebar.tsx`): grouped IA, sans labels, rounded
   active pill with mint dot, health dot moves to Connections, softer footer.
3. **Dashboard**: hero numbers in mono, cards to 16px radius glass, section order:
   agent activity → needs-review → health → shortcuts.
4. **Connections + Health merge**: health strip/tab inside connections; /health
   redirects.
5. **Page sweep** (all remaining pages): replace hard borders (`border-[#222]`,
   `rounded-none/sm`) with tokens/radius, uppercase-mono headers → sans headers via
   `page-header` component, keep mono on data.
6. **Verification screenshots** of every page; fix regressions.

## 5. Non-goals (this pass)
- No route renames beyond /health redirect; no feature changes; no light mode.
- Knowledge page keeps its own scoped design layer (already redesigned, already close
  to the target aesthetic) — only token alignment.
- Notebook embed (third-party UI) untouched.
