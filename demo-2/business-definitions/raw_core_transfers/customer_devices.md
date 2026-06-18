# raw_core_transfers.customer_devices

**Source system:** internal core product DB (Postgres)
**Grain:** one row per device registered to a customer (1-3 per customer)
**Approx rows (demo scale):** ~96,000
**Loaded by:** warehouse/generators/gen_raw_core_transfers.py

## Business definition
Devices a customer has used the NALA app from, with platform, app/OS version, push token, and last-seen IP. Used for fraud / trust signals and push notifications. Most customers have one device; some have two or three.

## Known data-quality quirks
- `last_seen_at` is an ISO-Z **string** (text), not a timestamptz — timezone drift, requires casting.
- `first_seen_epoch_ms` is an epoch-milliseconds **bigint**, not a timestamp — divide by 1000 before converting.
- `push_token` is ~30% null.
- `device_id` is a vendor device id string (text PK), e.g. `det_uuid(("device", cid, k))`.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| device_id | text | yes | Primary key; vendor device identifier |
| customer_id | bigint | no | -> customers.customer_id |
| platform | text | no | ios/android/web |
| app_version | text | no | NALA app version |
| os_version | text | no | OS version string |
| device_model | text | no | Device model (iPhone14,3, Pixel 7, ...) |
| push_token | text | yes | Push notification token (~30% null) |
| ip_address | inet | yes | Last-seen IP address |
| last_seen_at | text | no | ISO-Z string timestamp (not tz) |
| is_trusted | boolean | no | Trusted-device flag (~65% true) |
| first_seen_epoch_ms | bigint | no | First-seen time as epoch milliseconds |

## Joins / lineage
- `customer_id` -> customers.customer_id.
