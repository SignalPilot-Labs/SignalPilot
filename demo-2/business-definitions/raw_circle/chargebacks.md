# raw_circle.chargebacks

**Source system:** Circle (Payments API)
**Grain:** one row per chargeback/dispute against a card payment
**Approx rows (demo scale):** ~1.5% of paid card payments (single digits at test)
**Loaded by:** warehouse/generators/gen_raw_circle.py

## Business definition
Card disputes raised by cardholders/issuers against a Circle payment. Tracks category, network reason code, and lifecycle (pending -> under_review -> won/lost). Used for fraud and loss reporting.

## Known data-quality quirks
- `create_date`/`resolved_date` are ISO-Z STRINGS.
- `resolved_date` set only for won/lost.
- Low volume by design (real chargeback rates are <2%).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | PK, Circle chargeback uuid |
| payment_id | text | no | -> usdc_payments.id |
| merchant_wallet_id | text | no | -> usdc_wallets.wallet_id |
| amount | numeric(20,2) | no | Disputed amount |
| currency | text | no | Currency |
| category | text | no | Fraudulent / Authorization / Processing Error / Consumer Dispute |
| status | text | no | pending / under_review / won / lost |
| reason_code | text | no | Card network reason code (e.g. 10.4, 13.1) |
| create_date | text | no | ISO-Z string |
| resolved_date | text | no | ISO-Z string (won/lost only) |
| raw_payload | jsonb | no | Raw vendor payload |

## Joins / lineage
- `payment_id` -> raw_circle.usdc_payments.id.
- `merchant_wallet_id` -> raw_circle.usdc_wallets.
