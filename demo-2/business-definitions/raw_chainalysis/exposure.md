# raw_chainalysis.exposure

**Source system:** Chainalysis (crypto wallet risk screening — exposure breakdown)
**Grain:** one row per (screening, counterparty-category, direction) exposure breakdown line
**Approx rows (demo scale):** ~84,000 (each screening emits 2-5 exposure lines)
**Loaded by:** warehouse/generators/gen_raw_chainalysis.py

## Business definition
The counterparty-exposure breakdown for a wallet screening — how much USD value the screened address sent to or received from each counterparty category (exchange, mining, darknet market, sanctioned entity, scam, defi, ...). This is the detail behind a screening's overall risk rating and lets analysts see exactly which risky category drove the exposure.

## Known data-quality quirks
- `percentage` (0..1 share of total exposure) is ~30% null.
- `cluster_name` is ~50% null.
- `category` pool is the clean categories plus the parent screening's risk category when High/Severe.
- `direction` here is SENT/RECEIVED (note: differs from address_screenings.direction which is DEPOSIT/WITHDRAWAL).
- `value_usd` is numeric(20,2) USD; `created_at` is an ISO-8601 string.
- `id` is a surrogate bigserial.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigserial | no | PK, surrogate |
| screening_id | text | no | -> address_screenings.id |
| address | text | yes | denormalised wallet address (PII) |
| direction | text | no | SENT / RECEIVED |
| category | text | no | exchange / mining / gambling / sanctioned entity / darknet market / scam / defi / ... |
| exposure_type | text | no | DIRECT / INDIRECT |
| value_usd | numeric(20,2) | no | USD value exposed to this category |
| percentage | numeric(7,4) | no | share of total exposure 0..1 (~30% null) |
| cluster_name | text | no | attributed cluster (~50% null) |
| created_at | text | no | ISO-8601 string |

## Joins / lineage
- `screening_id` -> raw_chainalysis.address_screenings.id.
