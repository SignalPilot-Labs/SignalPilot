# raw_rafiki.merchant_users

**Source system:** Rafiki internal platform DB (auth/identity service)
**Grain:** one row per user with login access to a merchant account
**Approx rows (demo scale):** ~3,600 (119 at test scale)
**Loaded by:** warehouse/generators/gen_raw_rafiki.py

## Business definition
People who can log into the Rafiki dashboard for a merchant — owners, admins,
developers, finance and viewer roles. PII-heavy. Some merchant users are ALSO
consumer-app customers; when so, `canonical_cid` links to the canonical customer
master so identity-resolution demos can join B2B users to B2C accounts.

## Known data-quality quirks
- `email`/`phone` are dirtied (casing, dot drift, leading/trailing spaces, `00` prefixes).
- `last_login_at` is epoch milliseconds (auth service), ~10% null.
- `created` is an ISO-Z string.
- `invited_by` is null for the owner row.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| user_id | text | no | PK, `usr_<hex>` |
| merchant_id | text | no | Owning merchant |
| full_name | text | yes | User's name |
| email | text | yes | Login email (dirty) |
| phone | text | yes | Phone (dirty E.164) |
| role | text | no | owner/admin/developer/finance/viewer |
| canonical_cid | bigint | no | App customer id when user is also a B2C customer |
| last_login_at | bigint | no | Epoch ms |
| is_active | boolean | no | Active login |
| invited_by | text | no | Inviting user_id (null for owner) |
| created | text | no | ISO-Z string |
| mfa_enabled | boolean | no | MFA on |

## Joins / lineage
- Joins to `raw_rafiki.merchants` on `merchant_id`.
- Cross-source: `canonical_cid` -> canonical customer master (and any source keyed by cid).
