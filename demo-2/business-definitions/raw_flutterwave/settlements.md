# raw_flutterwave.settlements

**Source system:** Flutterwave v3 API (/settlements)
**Grain:** one row per settlement batch (per currency, ~weekly)
**Approx rows (demo scale):** ~1.1k
**Loaded by:** warehouse/generators/gen_raw_flutterwave.py

## Business definition
Settlement batches Flutterwave pays into NALA's collection account, aggregating
many transfers per currency per week. Carries gross/net and the fee breakdown
(app fee, merchant fee, chargebacks) used for revenue reconciliation.

## Known data-quality quirks
- Not every currency settles every week (~30% of slots skipped).
- `chargeback_amount` is 0.0 for most batches (only ~10% carry chargebacks).
- `settled_at` NULL while `status = 'pending'` (~8%).
- `net_amount = gross_amount - app_fee - merchant_fee - chargeback_amount`.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigint | no | PK |
| settlement_reference | text | no | batch reference `SETTLE-<CUR>-<date>` |
| currency | text | no | settlement currency |
| gross_amount | numeric(18,2) | no | total before fees |
| app_fee / merchant_fee | numeric(18,2) | no | Flutterwave fees |
| chargeback_amount | numeric(18,2) | no | clawbacks, usually 0 |
| net_amount | numeric(18,2) | no | amount actually paid out |
| transfer_count | integer | no | transfers in the batch |
| status | text | no | completed / pending |
| due_date | date | no | scheduled settlement date |
| settled_at | timestamptz | no | actual settlement time, NULL if pending |
| raw_payload | jsonb | no | vendor blob |

## Joins / lineage
- Aggregates `raw_flutterwave.transfers` by currency + window (not keyed line-by-line in raw).
