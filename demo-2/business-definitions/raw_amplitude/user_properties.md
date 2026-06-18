# raw_amplitude.user_properties

**Source system:** Amplitude
**Grain:** one row per `amplitude_id` (latest known property snapshot per user)
**Approx rows (demo scale):** ~60,000
**Loaded by:** warehouse/generators/gen_raw_amplitude.py

## Business definition
Denormalized profile snapshot of the latest known user properties per Amplitude user (plan, country, KYC status, lifetime transfers, paying flag). Used as a fast lookup for segmenting events by current user state without re-aggregating the event stream. Mutable in real life; loaded here as a point-in-time snapshot.

## Known data-quality quirks
- `user_id` is ~8% null (anon-only users that never identified).
- `cohort` is a legacy single-cohort label, deprecated, and ~50% null — prefer `raw_amplitude.cohorts`.
- `last_seen_at` is forced to be ≥ `first_seen_at` at generation.
- `properties` jsonb duplicates several flat columns (plan, country) plus kyc_status and lifetime_transfers.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| amplitude_id | bigint | yes | Amplitude internal user id (PK) |
| user_id | text | yes | `CUS_...` code; ~8% null (anon-only) |
| device_id | text | yes | Device id (maps to Segment anonymous_id) |
| first_seen_at | timestamptz | no | First-seen time (≈ signup) |
| last_seen_at | timestamptz | no | Last-seen time (≥ first_seen_at) |
| properties | jsonb | no | {plan, country, currency, kyc_status, lifetime_transfers, paying} |
| country | text | no | Country |
| city | text | no | City |
| platform | text | no | iOS / Android / Web |
| paying | boolean | no | Has completed ≥1 transfer |
| cohort | text | no | Legacy single-cohort label (deprecated, ~50% null) |

## Joins / lineage
- `amplitude_id` → `raw_amplitude.events.amplitude_id`.
- `user_id` = customer code → `common.customer_master`.
- `device_id` == `raw_segment` `anonymous_id` for cross-source stitching.
