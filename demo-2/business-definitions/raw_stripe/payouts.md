# raw_stripe.payouts

**Source system:** Stripe (Payouts API)
**Grain:** one row per payout from NALA's Stripe balance to its own bank account
**Approx rows (demo scale):** ~3k
**Loaded by:** warehouse/generators/gen_raw_stripe.py

## Business definition
Program-level settlements: Stripe pays NALA's accumulated card-funding balance out to NALA's operating bank account. Not per-customer — these are NALA's own cash-out events.

## Known data-quality quirks
- `created`/`arrival_date` are epoch **seconds**; `amount` MINOR units.
- `failure_code` only on failed payouts.
- `destination` is a Stripe bank account id `ba_...` (4 program accounts).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | `po_...` (PK) |
| object | text | no | 'payout' |
| created | bigint | no | epoch SECONDS |
| arrival_date | bigint | no | epoch SECONDS |
| amount | bigint | no | MINOR units |
| currency | text | no | lowercase ccy |
| status | text | no | paid/in_transit/pending/failed/canceled |
| type | text | no | bank_account/card |
| method | text | no | standard/instant |
| destination | text | no | `ba_...` bank account id |
| bank_name | text | no | destination bank |
| bank_last4 | text | yes | destination acct last4 |
| statement_descriptor | text | no | descriptor |
| failure_code | text | no | sparse |
| automatic | boolean | no | auto vs manual payout |
| metadata | jsonb | no | |

## Joins / lineage
- Standalone (program-level). No customer join.
