# raw_braze.custom_events

**Source system:** Braze
**Grain:** one row per tracked product/business event forwarded to Braze
**Approx rows (demo scale):** ~240,000 (customers × 4)
**Loaded by:** warehouse/generators/gen_raw_braze.py

## Business definition
Product and business events forwarded from NALA's apps into Braze to drive CRM triggers (e.g. `transfer_completed`, `transfer_initiated`, `kyc_passed`, `first_transfer`, `promo_redeemed`, `referral_sent`). Each row carries the event name, the customer, the originating app, and a semi-structured properties payload. Used to power event-triggered journeys and to analyze behavioral signals feeding CRM.

## Known data-quality quirks
- `"time"` is **epoch milliseconds** here — this deliberately drifts against `raw_braze.messages_sent."time"` (epoch seconds). Divide by 1000 before comparing or converting.
- `received_at` is ISO-8601 text with **no timezone** (legacy format); do not assume UTC blindly.
- `properties` is null for events that carry no payload (e.g. `app_opened`, `kyc_passed`); transfer/promo events embed a `transfer_id` (det_uuid) or `promo_code`.
- `transfer_id` lives inside the `properties` JSON, not as a top-level column.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigint | no | surrogate row id, primary key |
| external_user_id | text | no | NALA customer code 'CUS_XXXXXXXX' |
| name | text | no | event name, e.g. transfer_completed / kyc_passed |
| properties | jsonb | no | semi-structured payload (transfer_id, amount_usd, promo_code); nullable |
| app_id | text | no | nala-ios / nala-android / nala-web |
| time | bigint | no | epoch MILLISECONDS (drifts vs messages_sent epoch s) |
| received_at | text | no | ISO string, NO timezone (legacy) |

## Joins / lineage
- `external_user_id` = NALA customer code (`CUS_...`), the canonical customer join key.
- `properties->>'transfer_id'` = transfer UUID — links transfer-related events to the transfers fact (JSON extraction required).
