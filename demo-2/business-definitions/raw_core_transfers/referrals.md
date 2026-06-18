# raw_core_transfers.referrals

**Source system:** internal core product DB (Postgres)
**Grain:** one row per referral (a referrer inviting a referee)
**Approx rows (demo scale):** ~15,000
**Loaded by:** warehouse/generators/gen_raw_core_transfers.py

## Business definition
The referral graph: a referring customer (referrer) brings in a new customer (referee), optionally earning a reward once the referee qualifies via a transfer. Used for growth / virality analysis.

## Known data-quality quirks
- `status` is one of pending / qualified / rewarded / expired (rewarded weighted higher).
- `qualifying_transfer_id` is sparse — set only when status is `qualified` or `rewarded`.
- `rewarded_at` is null unless status is `rewarded`.
- Referrer and referee are guaranteed distinct (self-referral is corrected to a neighbor cid).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| referral_id | bigint | no | Primary key |
| referral_code_id | bigint | no | -> referral_codes.referral_code_id |
| referrer_cid | bigint | no | Referring customer -> customers.customer_id |
| referee_cid | bigint | no | New customer -> customers.customer_id |
| status | text | no | pending / qualified / rewarded / expired |
| reward_amount | numeric(18,2) | no | Reward amount |
| reward_currency | text | no | Reward currency |
| qualifying_transfer_id | uuid | no | -> transfers.transfer_id (sparse) |
| referred_at | timestamptz | no | Referral time |
| rewarded_at | timestamptz | no | Reward time (null unless rewarded) |

## Joins / lineage
- `referrer_cid` and `referee_cid` -> customers.customer_id.
- `referral_code_id` -> referral_codes.referral_code_id.
- `qualifying_transfer_id` -> transfers.transfer_id.
