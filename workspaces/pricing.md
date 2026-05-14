# SignalPilot Workspaces — Pricing Framework

Framework only. Numbers are placeholders until post-MVP unit economics are measured. All `# TBD post-MVP` items require empirical usage data before locking.

---

## Pricing Axes

Four billable dimensions:

1. **Seats** — number of users with access to Workspaces within an org.
2. **Workspaces / projects** — concurrent active workspaces and linked dbt projects.
3. **Inference usage** — LLM tokens consumed per agent run (input + output). Charged at cost-plus margin for metered mode; zero for BYO API key.
4. **Storage** — `workspaces-data` volume: dbt project clones, chart cache, Arrow result payloads.

---

## Tier Shape

| Tier | Seats | Workspaces | Inference | Storage |
|------|-------|------------|-----------|---------|
| Free | # TBD post-MVP | # TBD post-MVP | BYO key only | # TBD post-MVP GB |
| Pro | # TBD post-MVP | # TBD post-MVP | BYO or metered | # TBD post-MVP GB |
| Team | # TBD post-MVP | # TBD post-MVP | BYO or metered | # TBD post-MVP GB |
| Enterprise | Unlimited | Unlimited | Negotiated | Negotiated |

All tiers include: approval gates, credential isolation, SSE event streaming, ECharts dashboard editor.
Team and above include: SSO, audit log export, dbt Cloud link, private deployment option.

---

## Entity Sketches

These types will be implemented in a future billing round. Defined here so the data model is clear before implementation.

```
PricingTier
  id: str
  name: str                    # "free" | "pro" | "team" | "enterprise"
  seat_limit: int | None       # None = unlimited
  workspace_limit: int | None
  storage_limit_gb: int | None
  metered_inference: bool

MeteredEvent
  id: uuid
  org_id: str
  run_id: str
  event_type: str              # "inference_tokens" | "storage_bytes"
  quantity: int
  recorded_at: datetime

UsageWindow
  org_id: str
  period_start: datetime
  period_end: datetime
  inference_tokens: int
  storage_bytes: int
  seats_active: int
```

---

## Open Questions

1. **Inference margin** — what markup on Anthropic cost is sustainable at scale? Requires usage data from beta. # TBD post-MVP
2. **Hard caps vs soft alerts** — does inference usage block the run at limit, or send a warning and continue? Hard caps are simpler to implement and avoid surprise bills; soft alerts reduce user friction. # TBD post-MVP
3. **Per-run budget enforcement point** — gateway-side (governance ledger already exists in `gateway/governance/`) or workspaces-api side? Gateway enforcement is stricter but adds latency per tool call. # TBD post-MVP
4. **Free tier inference** — does free tier get any metered inference, or is it BYO-key-only? Affects acquisition funnel. # TBD post-MVP
5. **Storage metering granularity** — bill on peak, average, or end-of-period snapshot? Arrow cache is write-heavy and short-lived. # TBD post-MVP
