# raw_sendgrid.messages

**Source system:** Twilio SendGrid v3 Mail Send API
**Grain:** one row per email send
**Approx rows (demo scale):** ~3,000,000 (sized off `N["transfers"]`)
**Loaded by:** warehouse/generators/gen_raw_sendgrid.py

## Business definition
Every email NALA sends — OTP, transfer receipts, KYC prompts, lifecycle notifications, and marketing. One row per send with denormalized engagement rollups (`opens_count`, `clicks_count`); the per-event detail lives in `raw_sendgrid.events`.

## Known data-quality quirks
- `to_email` is a customer email through `dirty_email` — casing/dot/leading-space drift. Normalize (lower + trim) before joining.
- `sent_at` is an ISO-8601 Z string, not timestamptz.
- `customer_id` ~90% resolved.
- `asm_group_id` sparse (mostly on marketing).
- `opens_count`/`clicks_count` are rollups and can lag the raw event stream.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| sg_message_id | text | no | SendGrid message id (PK) |
| to_email | text | yes | recipient email (dirty) |
| from_email | text | no | NALA sending address by category |
| subject | text | no | email subject |
| template_id | text | no | dynamic template `d-...` |
| category | text | no | otp/receipt/kyc/notification/marketing |
| asm_group_id | integer | no | unsubscribe group (sparse) |
| msg_status | text | no | processed/delivered/bounce/dropped |
| opens_count | integer | no | denormalized open rollup |
| clicks_count | integer | no | denormalized click rollup |
| customer_id | bigint | no | resolved canonical cid (~10% NULL) |
| ip_pool | text | no | sending IP pool name |
| is_marketing | boolean | no | marketing vs transactional |
| sent_at | text | no | ISO-Z string |
| raw_payload | jsonb | no | mail-send request blob |

## Joins / lineage
- Joins to `raw_sendgrid.events` on `sg_message_id`.
- Joins to canonical customer on `customer_id`, or normalized `to_email` ↔ `customer_master.email`.
