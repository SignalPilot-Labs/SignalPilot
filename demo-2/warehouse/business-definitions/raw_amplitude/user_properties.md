# raw_amplitude.user_properties

**Source system:** Amplitude (user-property export)
**Grain:** one row per `amplitude_id` (one per user)
**Approx rows (demo scale):** ~60,000 (`N["customers"]`)
**Loaded by:** warehouse/generators/gen_raw_amplitude.py

## Business definition
A denormalized snapshot of the latest known Amplitude user properties — plan, country, KYC status, lifetime transfers, paying flag, first/last seen. Used to segment users and enrich event analysis without re-deriving traits.

## Known data-quality quirks
- `user_id` ~8% null (anon-only users that never identified).
- `cohort` is a deprecated single-label column (~50% null); real cohorts live in `raw_amplitude.cohorts`.
- It is a snapshot — values are point-in-time, not historized.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| amplitude_id | bigint | no | Amplitude internal user id. PK. |
| user_id | text | yes | Customer code CUS_...; ~8% null. |
| device_id | text | yes | Device id. |
| first_seen_at | timestamptz | no | First event time. |
| last_seen_at | timestamptz | no | Most recent event time. |
| properties | jsonb | maybe | Profile blob (plan, country, kyc_status, lifetime_transfers). |
| country / city | text | no | Geo. |
| platform | text | no | iOS / Android / Web. |
| paying | boolean | no | Has completed ≥1 transfer. |
| cohort | text | no | Deprecated single-cohort label. |

## Joins / lineage
- `amplitude_id` → `raw_amplitude.events.amplitude_id`.
- `user_id` → `raw_core_transfers.customers.customer_code`.
- No staging model (low-priority table).
