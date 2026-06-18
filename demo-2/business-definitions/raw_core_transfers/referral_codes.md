# raw_core_transfers.referral_codes

**Source system:** internal core product DB (Postgres)
**Grain:** one row per shareable referral code owned by a customer
**Approx rows (demo scale):** ~3,000
**Loaded by:** warehouse/generators/gen_raw_core_transfers.py

## Business definition
The referral codes customers share to invite others, with reward terms and redemption caps. Each code is owned by a customer (`owner_cid`). Count scales as customers / 20 (min 50).

## Known data-quality quirks
- `code` is derived from the owner's first name + a random number (e.g. `BEN2024`) and is not guaranteed unique.
- `times_redeemed` is a random value between 0 and `max_redemptions` (not a live counter).
- `is_active` is true ~85% of the time.
- `expires_at` is far in the future relative to `created_at` (120-800 days).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| referral_code_id | bigint | no | Primary key |
| code | text | no | Shareable code (e.g. BEN2024) |
| owner_cid | bigint | no | Code owner -> customers.customer_id |
| reward_amount | numeric(18,2) | no | Reward per redemption |
| reward_currency | text | no | Reward currency (owner's currency) |
| max_redemptions | integer | no | Redemption cap |
| times_redeemed | integer | no | Times redeemed (0..max) |
| is_active | boolean | no | Active flag (~85% true) |
| created_at | timestamptz | no | Creation time |
| expires_at | timestamptz | no | Expiry time |

## Joins / lineage
- `owner_cid` -> customers.customer_id.
- `referral_code_id` is referenced by referrals.referral_code_id.
