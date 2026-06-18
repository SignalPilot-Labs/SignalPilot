# raw_rafiki.webhook_deliveries

**Source system:** Rafiki webhook/events service
**Grain:** one row per webhook delivery attempt
**Approx rows (demo scale):** ~tens of thousands (661 at test scale)
**Loaded by:** warehouse/generators/gen_raw_rafiki.py

## Business definition
Individual attempts to deliver an event to a merchant's webhook endpoint, with HTTP
response status, attempt number, success flag and latency. Failed deliveries carry a
retry time. A fact table for webhook reliability analytics.

## Known data-quality quirks
- `response_status` can be null on timeout / connection failure.
- `delivered_at` and `next_retry_at` are epoch milliseconds; `next_retry_at` null on success.
- Multiple attempts per event when failing.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| delivery_id | text | no | PK, `whd_<hex>` |
| webhook_id | text | no | Parent webhook |
| merchant_id | text | no | Owning merchant |
| event_type | text | no | collection.confirmed/payout.paid/... |
| event_id | text | no | Event identifier |
| response_status | integer | no | HTTP status (null on timeout) |
| attempt | integer | no | Attempt number |
| success | boolean | no | Delivered successfully |
| duration_ms | integer | no | Latency |
| delivered_at | bigint | no | Epoch ms |
| next_retry_at | bigint | no | Epoch ms (null on success) |

## Joins / lineage
- Joins to `raw_rafiki.webhooks` on `webhook_id` and `raw_rafiki.merchants` on `merchant_id`.
