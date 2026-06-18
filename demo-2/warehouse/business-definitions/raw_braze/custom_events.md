# raw_braze.custom_events

**Source system:** Braze (custom event ingestion / Currents)
**Grain:** one row per tracked custom event for a customer
**Approx rows (demo scale):** ~240,000 (N["customers"] × 4)
**Loaded by:** warehouse/generators/gen_raw_braze.py

## Business definition
Product/business events forwarded into Braze (e.g. `transfer_completed`,
`kyc_passed`) used to trigger and segment campaigns. Some events carry a
`transfer_id` in `properties` linking marketing to core transfers.

## Known data-quality quirks
- `time` is **epoch milliseconds** here — drift vs `messages_sent.time` (epoch seconds).
- `received_at` is an ISO string with **no timezone** (legacy).
- `properties` JSON shape varies by event `name`; many rows have NULL properties.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | bigint | no | surrogate PK |
| external_user_id | text | no | NALA customer code (join key) |
| name | text | no | event name e.g. transfer_completed |
| properties | jsonb | no | semi-structured payload, sparse |
| app_id | text | no | nala-ios / nala-android / nala-web |
| time | bigint | no | epoch **milliseconds** |
| received_at | text | no | ISO string, no tz |

## Joins / lineage
- `external_user_id` → NALA customer code.
- `properties->>'transfer_id'` → core transfers transfer_id (det_uuid), when present.
