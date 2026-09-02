/**
 * What the chat markdown renderer supports, in one document. Everything here
 * is standard GitHub Flavored Markdown, standard HTML, or a fenced block in a
 * language models already write unprompted — nothing house-specific.
 *
 * It backs the /chats/markdown page and the e2e coverage for the renderer.
 */

export type ShowcaseSection = {
  id: string;
  title: string;
  markdown: string;
};

export const SHOWCASE_SECTIONS: ShowcaseSection[] = [
  {
    id: "answer",
    title: "Full answer",
    markdown: `June revenue was **$1,314,559** across 12,733 completed orders, down
0.4% from May even though order count fell 2.1%. The gap is refunds: the refund
rate went from 2.4% to 3.8% after a batch of marketplace returns settled late.

### How this number was computed

Read from \`analytics.fct_orders\` at commit \`a41f9c2\`, one row per
\`order_id\`, filtered to \`order_status = 'completed'\`. Refunds join
\`stg_refunds\` on \`(order_id, line_id)\` — joining on \`order_id\` alone
duplicates multi-line orders and overstates revenue by ~1.8%.

\`\`\`sql title="monthly revenue and refund rate"
select
    date_trunc('month', order_date)      as order_month,
    count(distinct order_id)             as order_count,
    sum(order_total)                     as gross_revenue,
    sum(refund_total) / sum(order_total) as refund_rate
from analytics.fct_orders o
left join analytics.stg_refunds r
  on r.order_id = o.order_id and r.line_id = o.line_id
where order_status = 'completed'
  and order_date >= '2026-01-01'
group by 1
order by 1
\`\`\`

| Month | Orders | Gross revenue | Refund rate |
| --- | ---: | ---: | ---: |
| 2026-04 | 12,481 | $1,204,882 | 2.1% |
| 2026-05 | 13,006 | $1,262,140 | 2.4% |
| 2026-06 | 12,733 | $1,314,559 | 3.8% |

Row count 12,733 equals \`count(distinct order_id)\`, so the grain holds. No
null \`order_total\`. Freshness: 2026-06-30 23:00 UTC.

<details>
<summary>Assumptions, exclusions and caveats</summary>

- Test orders excluded (\`is_test = true\`), 412 rows
- Refunds attributed to the month of the original order, not settlement
- Currency converted at the daily close rate
- June is a **partial comparison**: the last load is 2026-06-30 23:00 UTC

</details>

<details>
<summary>Lineage for the models behind this answer</summary>

\`\`\`mermaid
flowchart LR
  raw[raw.shopify.orders] --> stg[stg_orders]
  raw2[raw.shopify.refunds] --> stg2[stg_refunds]
  stg --> fct[fct_orders]
  stg2 --> fct
  fct --> mart[mart_orders_daily]
\`\`\`

</details>

> Refunds are recognised in the month of the original order, not the month the
> refund settles. — Finance definitions, 2026-01-14
`,
  },
  {
    id: "prose",
    title: "Prose & GFM",
    markdown: `## Revenue reconciliation

The **June** figure moved by _4.1%_ after the late-arriving refunds landed. See
[fct_orders](/lineage/fct_orders) for the model that produces it.

- Grain: one row per \`order_id\`
- Source: \`raw.shopify.orders\`, loaded hourly
- Excluded: test orders (\`is_test = true\`), 412 rows

1. Pull the orders
2. Join the refunds
3. Aggregate to month

- [x] Row count checked
- [x] Null audit clean
- [ ] Fan-out check pending

| Month | Orders | Revenue | Refund rate |
| --- | ---: | ---: | ---: |
| 2026-04 | 12,481 | $1,204,882 | 2.1% |
| 2026-05 | 13,006 | $1,262,140 | 2.4% |
| 2026-06 | 12,733 | $1,314,559 | 3.8% |

> Refunds are recognised in the month of the original order, not the month the
> refund settles.

Footnotes work too.[^grain]

[^grain]: Grain was verified with a \`count(*)\` vs \`count(distinct order_id)\` check.
`,
  },
  {
    id: "html",
    title: "Inline HTML",
    markdown: `Press <kbd>⌘</kbd> + <kbd>K</kbd> to search models.
The <abbr title="Annual Recurring Revenue">ARR</abbr> figure is
<mark>unaudited</mark>, and the tax line uses the H<sub>2</sub> rate<sup>1</sup>.

<dl>
<dt>Freshness</dt>
<dd>2026-06-30 23:00 UTC</dd>
<dt>Completeness</dt>
<dd>Complete</dd>
</dl>

Alignment and grouping that GFM tables cannot express:

<table>
<caption>Refunds by channel and month</caption>
<thead>
<tr><th rowspan="2">Channel</th><th colspan="2">Refunds</th></tr>
<tr><th>May</th><th>June</th></tr>
</thead>
<tbody>
<tr><td>Direct</td><td>141</td><td>236</td></tr>
<tr><td>Marketplace</td><td>171</td><td>248</td></tr>
</tbody>
</table>

<figure>
<blockquote>A refund belongs to the month of the order it reverses.</blockquote>
<figcaption>Finance definitions, 2026-01-14</figcaption>
</figure>
`,
  },
  {
    id: "disclosures",
    title: "Dropdowns",
    markdown: `<details>
<summary>Assumptions and exclusions</summary>

- Test orders excluded (\`is_test = true\`)
- Refunds attributed to the original order month
- Currency converted at the daily close rate
- Rows after 2026-06-30 excluded

</details>

<details open>
<summary>Full SQL</summary>

\`\`\`sql
select date_trunc('month', o.ordered_at) as month,
       count(distinct o.order_id)        as orders,
       sum(o.net_revenue)                as revenue
from fct_orders o
where o.is_test = false
group by 1
order by 1
\`\`\`

</details>

<details>
<summary>Verification checks</summary>

Anything nested here is still markdown — **including tables**.

| check | result |
| --- | --- |
| row count | 12,733 |
| distinct keys | 12,733 |
| null net_revenue | 0 |

</details>
`,
  },
  {
    id: "code",
    title: "Code, SQL & diffs",
    markdown: `\`\`\`sql title="monthly revenue"
select date_trunc('month', ordered_at) as month,
       sum(net_revenue)                as revenue
from fct_orders
where is_test = false
group by 1
\`\`\`

\`\`\`python
import pandas as pd

frame = pd.DataFrame(source["rows"])
frame["month"] = pd.to_datetime(frame["month"])
frame.describe()
\`\`\`

\`\`\`bash
dbt build --select fct_orders+ --target prod
\`\`\`

\`\`\`diff
--- a/models/marts/fct_orders.sql
+++ b/models/marts/fct_orders.sql
@@ -18,7 +18,7 @@
 left join stg_refunds r
-  on r.order_id = o.order_id
+  on r.order_id = o.order_id and r.line_id = o.line_id
\`\`\`
`,
  },
  {
    id: "diagrams",
    title: "Diagrams & math",
    markdown: `\`\`\`mermaid
flowchart LR
  raw[raw.shopify.orders] --> stg[stg_orders]
  raw2[raw.shopify.refunds] --> stg2[stg_refunds]
  stg --> fct[fct_orders]
  stg2 --> fct
  fct --> mart[mart_orders_daily]
\`\`\`

\`\`\`mermaid
sequenceDiagram
  participant U as User
  participant A as Agent
  participant W as Warehouse
  U->>A: What moved June revenue?
  A->>W: governed aggregate
  W-->>A: 12,733 rows
  A-->>U: answer + evidence
\`\`\`

The refund rate is defined as

$$
r_{month} = \\frac{\\sum refunds}{\\sum orders}
$$

so a \\$1,000 refund on a \\$26,000 base moves it by 3.8 points. Inline math
uses double dollars too: $$r = 0.038$$ — single \\$ signs stay currency.
`,
  },
];

export const SHOWCASE_MARKDOWN = SHOWCASE_SECTIONS.map(
  (section) => `# ${section.title}\n\n${section.markdown}`,
).join("\n\n");
