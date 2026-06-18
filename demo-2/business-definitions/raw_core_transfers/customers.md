# raw_core_transfers.customers

**Source system:** internal core product DB (Postgres)
**Grain:** one row per sending customer (canonical cid)
**Approx rows (demo scale):** ~60,000
**Loaded by:** warehouse/generators/gen_raw_core_transfers.py

## Business definition
The sender accounts that originate transfers. PII-heavy: full name, email, phone, date of birth, and national id. Derived from `common.customer_master()`, so the same canonical cid is referenced across every domain in the warehouse.

## Known data-quality quirks
- `email` is dirtied (casing / whitespace drift) and ~4% null.
- `phone` is dirtied (inconsistent format), never null.
- `national_id` is ~10% null; `national_id_hash` is a partial-governance hash mimic (not a real secure hash).
- `account_status` is free text (`active`/`suspended`/`closed`), weighted toward active.
- Soft delete: `is_deleted` (~3% true) with `deleted_at` populated only when deleted.
- `kyc_tier` is randomly assigned and may disagree with customer_kyc_status.tier.
- `raw_attributes` is a denormalized jsonb snapshot (acquisition, lang, lifetime_transfers).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| customer_id | bigint | no | Primary key; canonical cid |
| customer_uuid | uuid | no | Customer UUID |
| customer_code | text | no | Human code, format `CUS_00000123` |
| first_name | text | yes | Sender first name |
| last_name | text | yes | Sender last name |
| email | text | yes | Email (dirty; ~4% null) |
| phone | text | yes | Phone (dirty format) |
| date_of_birth | date | yes | Date of birth |
| country | text | no | Send-from country |
| currency | text | no | Default debit currency |
| national_id | text | yes | National id (~10% null) |
| national_id_hash | text | yes | Partial-governance hash mimic of national_id |
| kyc_tier | text | no | tier0/tier1/tier2/tier3 |
| account_status | text | no | active/suspended/closed (free text) |
| signup_platform | text | no | ios/android/web |
| signup_country | text | no | Signup country |
| marketing_opt_in | boolean | no | Marketing consent flag |
| is_deleted | boolean | no | Soft-delete flag (~3% true) |
| deleted_at | timestamptz | no | Soft-delete time (null unless deleted) |
| created_at | timestamptz | no | Signup time |
| updated_at | timestamptz | no | Last update |
| raw_attributes | jsonb | no | Denormalized snapshot blob |

## Joins / lineage
- `customer_id` is referenced by transfers, recipients, customer_addresses, customer_devices, customer_kyc_status, quotes, promo_redemptions, referral_codes.owner_cid, referrals.referrer_cid/referee_cid, and by other warehouse domains via the shared canonical cid.
- Sourced from `common.customer_master()`.
