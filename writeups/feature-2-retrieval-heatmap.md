# Feature 2 — KB Doc Retrieval Heatmap

**Status:** Built, verified live in docker (screenshots), reviewed by 8-ideation + 8-review agent panel.

## What was built

The roadmap item #5 ("Retrieval heat-map UI — which KB docs agents actually use,
staleness flags") on top of Feature 1's retrieval-event pipeline.

### Backend
- `RetrievalDocStats` / `RetrievalStats` pydantic models (`gateway/models/knowledge.py`)
  typing the previously ad-hoc `/api/knowledge/retrievals` response end-to-end.
- `retrieval_stats` now **joins to active docs** — events for since-archived/deleted docs
  no longer inflate totals the UI can't attribute to a visible row (panel finding).

### Frontend (`/knowledge` → Insights → Retrieval heat)
- New nav kind `usage`; the heat view replaces the list+reader panes.
- Per-doc rows: category dot, scope, **daily heat cells** (oldest→newest, mint intensity
  sqrt-scaled against the global max), total pulls, by-source chips (baseline load /
  task match / search / read), last-pulled age. Click → opens the doc in its category.
- Range selector 7/30/90d. Series >32 cells are **client-side compressed** into
  multi-day buckets (fixes 90d grid overflow; tooltips show the day range).
- **Cold-docs section**: active docs with zero pulls in the window, *excluding docs
  created inside the window* (a day-old doc is not "stale"), sorted oldest-updated
  first — the archive-candidate queue. Human browsing is never counted (agent-signal
  purity, carried from Feature 1).
- Distinct loading / error / empty states (SWR error no longer masquerades as
  "no retrievals"; nothing flashes cold while data loads).

## Panel outcomes (16 agents, ~616k tokens)

Applied:
- **Cold-flash bug** (4 agents independently): everything showed as stale during load /
  range switch → derived data now gated on `data` presence.
- **90d overflow**: ~808px of fixed-width cells overflowed the grid → series compression.
- **Error state unhandled** → explicit error branch.
- **New docs flagged stale** → created_at-aware split + note.
- **Header totals vs rows disagreement** (archived-doc events) → active-doc join server-side
  + rows-derived total client-side.
- **Implicit sort contract** → explicit `total desc` sort in the memo.
- **Dirty-edit guard bypass on heat click** → dedicated `handleHeatSelect` honoring the guard.
- **Multi-org repo-link ambiguity in new github store helpers** → deterministic
  `ORDER BY created_at` (applies to Feature 3 files).

Deliberately not applied (backlog, best of ideation):
1. **Aggregate header row + column hover** — 2D exploration, "what happened Tuesday" (high/medium)
2. **Bulk archive from the cold section** — turns report into curation tool (high/medium)
3. **Retrieval-impact guard in the archive confirm dialog** — "pulled 47× this month" warning
   + wikilink-backlink warning (high/small)
4. **Hot-but-stale review queue** — pulled constantly but not edited in 90d (medium/medium)
5. **Trend deltas** (▲/▼ vs previous window) + "newly cold" badge (high/medium)
6. **Per-source series filtering** (needs series_by_source from backend) (medium/medium)
7. **Cold-count badge on the Insights nav item** (small)
8. Calendar-aligned buckets (rolling 24h windows today; noted, cosmetic at current scale).

## Verification
- 31 gateway tests pass (incl. new archived-doc-exclusion stats test).
- `tsc` clean for all touched files (remaining errors pre-exist in notebook/, e2e/).
- Live docker screenshots before and after the fix pass: heat rows with real agent
  retrieval data (get_knowledge + search_knowledge events), correct cold-section
  behavior (day-old doc excluded after fix).
