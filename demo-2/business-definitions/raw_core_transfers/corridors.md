# raw_core_transfers.corridors

**Source system:** internal core product DB (Postgres)
**Grain:** one row per supported send-currency x receive-market corridor
**Approx rows (demo scale):** ~48
**Loaded by:** warehouse/generators/gen_raw_core_transfers.py

## Business definition
A lookup of the money-movement corridors NALA supports: every send currency (GBP/USD/EUR) crossed with every receive market (16 countries). Defines the default rail and currencies for each lane. Count = 3 send currencies x 16 receive markets.

## Known data-quality quirks
- `corridor_code` is `{send_country}_{receive_country}` using a single representative send country per currency (e.g. GB for GBP, US for USD).
- All corridors are `is_active = true` in demo data.
- `launched_on` is a date; `created_at` is a timestamptz — both seeded between 2018 and 2022.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| corridor_id | bigint | no | Primary key |
| corridor_code | text | no | e.g. GB_KE, US_NG |
| send_country | text | no | Representative send country |
| send_currency | text | no | Send currency |
| receive_country | text | no | Receive country (ISO2) |
| receive_currency | text | no | Receive currency |
| default_rail | text | no | Default payout rail for the corridor |
| is_active | boolean | no | Active flag (all true in demo) |
| launched_on | date | no | Corridor launch date |
| created_at | timestamptz | no | Record creation time |

## Joins / lineage
- `corridor_id` is referenced by transfers.corridor_id.
