# raw_stripe.balance_transactions

**Source system:** Stripe (Balance Transactions API)
**Grain:** one row per movement on NALA's Stripe balance (charge, refund, payout, fee)
**Approx rows (demo scale):** ~890k
**Loaded by:** warehouse/generators/gen_raw_stripe.py

## Business definition
The ledger of every credit/debit to NALA's Stripe balance. Each successful charge produces a positive entry (with a Stripe fee deducted in `net`); refunds and payouts produce negatives. This is the source of truth for Stripe-side cash and fee reconciliation.

## Known data-quality quirks
- `created`/`available_on` are epoch **seconds**.
- `amount`/`net`/`fee` are MINOR units; `amount` is signed.
- `source` points at the originating object (`ch_`/`re_`/`po_`).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | `txn_...` (PK) |
| object | text | no | 'balance_transaction' |
| created | bigint | no | epoch SECONDS |
| available_on | bigint | no | epoch SECONDS funds clear |
| amount | bigint | no | signed, MINOR units |
| net | bigint | no | amount - fee, MINOR units |
| fee | bigint | no | Stripe fee, MINOR units |
| currency | text | no | lowercase ccy |
| type | text | no | charge/refund/payout/adjustment/stripe_fee |
| status | text | no | available/pending |
| source | text | no | originating object id |
| reporting_category | text | no | reporting bucket |
| description | text | no | free text |

## Joins / lineage
- `source` -> `raw_stripe.charges.id` / `refunds.id` / `payouts.id`.
- Referenced by `charges.balance_transaction`, `refunds.balance_transaction`.
