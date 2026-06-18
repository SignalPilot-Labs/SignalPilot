# raw_rafiki.merchant_api_keys

**Source system:** Rafiki internal platform DB (auth/credentials service)
**Grain:** one row per issued API key
**Approx rows (demo scale):** ~3,000 (94 at test scale)
**Loaded by:** warehouse/generators/gen_raw_rafiki.py

## Business definition
API credentials merchants use to call the Rafiki API. Stores only a user-visible
prefix and a sha256-style hash of the full key — never the raw secret (governed
design). Keys are scoped (live/test) and can be revoked.

## Known data-quality quirks
- `last_used_at` ~15% null (never-used keys).
- `revoked_at` only set when `revoked = true`.
- `scopes` is a JSON array string.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| api_key_id | text | no | PK, `ak_<hex>` |
| merchant_id | text | no | Owning merchant |
| key_prefix | text | yes | User-visible prefix `rk_live_xxxx` |
| key_hash | text | yes | Hash of full key |
| mode | text | no | live/test |
| scopes | jsonb | no | Array of scope strings |
| label | text | no | Human label |
| created_by | text | no | user_id that created the key |
| last_used_at | timestamptz | no | Last use (sparse) |
| revoked | boolean | no | Revoked flag |
| revoked_at | timestamptz | no | Revocation time |
| created_at | timestamptz | no | Issue time |

## Joins / lineage
- Joins to `raw_rafiki.merchants` on `merchant_id`; `created_by` -> `merchant_users.user_id`.
