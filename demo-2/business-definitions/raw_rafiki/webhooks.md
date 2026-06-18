# raw_rafiki.webhooks

**Source system:** Rafiki webhook/events service
**Grain:** one row per configured webhook endpoint
**Approx rows (demo scale):** ~thousands (41 at test scale)
**Loaded by:** warehouse/generators/gen_raw_rafiki.py

## Business definition
Merchant-configured HTTP endpoints that receive Rafiki event notifications
(collection confirmed, payout paid, settlement created, etc.). Each stores the
subscribed event types and a signing-secret hash.

## Known data-quality quirks
- Not every merchant configures a webhook (~25% have none).
- `disabled_at` only set when `is_active = false`.
- `events` is a JSON array string.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| webhook_id | text | no | PK, `wh_<hex>` |
| merchant_id | text | no | Owning merchant |
| url | text | no | Endpoint URL |
| events | jsonb | no | Subscribed event types |
| secret_hash | text | yes | Signing secret hash |
| is_active | boolean | no | Active flag |
| api_version | text | no | Pinned API version |
| created_at | timestamptz | no | Creation time |
| disabled_at | timestamptz | no | Disable time |

## Joins / lineage
- Joins to `raw_rafiki.merchants` on `merchant_id`; parent of `webhook_deliveries`.
