# raw_chainalysis.exposure

**Source system:** Chainalysis (crypto risk)
**Grain:** one row per (screening, counterparty-category, direction) exposure line
**Approx rows (demo scale):** ~78k (2-5 lines per screening)
**Loaded by:** warehouse/generators/gen_raw_chainalysis.py

## Business definition
The exposure breakdown for a screened address: how much USD value the address has
sent to / received from each counterparty category (exchange, mixing, darknet, etc.),
direct vs indirect. The substance behind a screening's risk rating.

## Known data-quality quirks
- `percentage` (share of total exposure) ~30% null.
- `cluster_name` ~50% null.
- `created_at` is an ISO-8601 string.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigserial | no | surrogate PK |
| screening_id | text | no | -> address_screenings.id |
| address | text | yes | denormalised wallet address |
| direction | text | no | SENT / RECEIVED |
| category | text | no | exchange / mixing / darknet market / scam / defi / ... |
| exposure_type | text | no | DIRECT / INDIRECT |
| value_usd | numeric(20,2) | no | USD value exposed to this category |
| percentage | numeric(7,4) | no | share of total exposure (0..1; ~30% null) |
| cluster_name | text | no | attributed cluster (~50% null) |
| created_at | text | no | ISO-8601 string |

## Joins / lineage
- Joins to `raw_chainalysis.address_screenings` on `screening_id`.
