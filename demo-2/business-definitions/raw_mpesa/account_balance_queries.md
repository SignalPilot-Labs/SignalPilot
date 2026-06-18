# raw_mpesa.account_balance_queries

**Source system:** Safaricom M-PESA Daraja API (/mpesa/accountbalance/v1/query)
**Grain:** one row per account-balance poll (per shortcode, ~every 3 days)
**Approx rows (demo scale):** ~840 (KE + TZ shortcodes, 2023→today)
**Loaded by:** warehouse/generators/gen_raw_mpesa.py

## Business definition
Periodic treasury polls of NALA's M-PESA shortcode float (working / utility /
charges accounts). Used to monitor payout liquidity per market.

## Known data-quality quirks
- `BOCompletedTime` is `yyyyMMddHHmmss` string.
- Three distinct float buckets (`WorkingAccountBalance`, `UtilityAccountBalance`, `ChargesPaidAccountBalance`) — M-PESA's account model.
- Snapshot cadence is sparse (~every 3 days), not continuous.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| OriginatorConversationID | text | no | PK |
| ConversationID | text | no | Daraja conversation id |
| BusinessShortCode | text | no | NALA shortcode |
| ResultCode | integer | no | query result |
| ResultDesc | text | no | result text |
| WorkingAccountBalance | numeric(18,2) | no | main float |
| UtilityAccountBalance | numeric(18,2) | no | utility float |
| ChargesPaidAccountBalance | numeric(18,2) | no | charges float |
| BalanceCurrency | text | no | KES / TZS |
| BOCompletedTime | text | no | `yyyyMMddHHmmss` string |
| queried_at | timestamptz | no | when we polled |
| raw_payload | jsonb | no | vendor blob |

## Joins / lineage
- Standalone treasury table. Joins to nothing operationally; aligns to `statements` by shortcode + date.
