# raw_rafiki.merchants

**Source system:** Rafiki internal platform DB (merchant service)
**Grain:** one row per onboarded B2B merchant
**Approx rows (demo scale):** ~1,200 (40 at test scale)
**Loaded by:** warehouse/generators/gen_raw_rafiki.py

## Business definition
The set of global businesses that use Rafiki's B2B API to accept stablecoins and
pay out in local currencies. Each merchant has a tier (standard/scale/enterprise),
an HQ country, a default settlement currency, and the stablecoins it accepts.
Drives volume sizing for collections, payouts, settlements and invoicing.

## Known data-quality quirks
- `accepts_stablecoins` is a legacy CSV string (e.g. `'USDC,USDT'`), not an array.
- `status` carries legacy value `'PENDING_KYB'` alongside active/suspended/churned.
- `created_at` is ISO with tz; `updated` is a legacy ISO string with NO timezone.
- `website` ~15% null, `account_manager` ~20% null.
- Churned merchants are sometimes soft-deleted (`is_deleted`/`deleted_at`).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| merchant_id | text | no | PK, `mrc_<hex>` |
| legal_name | text | no | Registered legal name |
| display_name | text | no | Dashboard display name |
| website | text | no | Marketing URL (sparse) |
| country | text | no | HQ country (send-from market) |
| default_settlement_currency | text | no | Local payout currency |
| accepts_stablecoins | text | no | Legacy CSV of accepted stablecoins |
| industry | text | no | Vertical |
| status | text | no | active/suspended/churned/PENDING_KYB |
| tier | text | no | standard/scale/enterprise |
| mrr_usd | numeric | no | Monthly recurring revenue (USD) |
| account_manager | text | yes | AM name (sparse) |
| is_test | boolean | no | Sandbox-only account |
| is_deleted | boolean | no | Soft-delete flag |
| deleted_at | timestamptz | no | Soft-delete time |
| metadata | jsonb | no | Vendor payload blob |
| created_at | timestamptz | no | Signup time (ISO tz) |
| updated | text | no | Legacy updated time (ISO, no tz) |

## Joins / lineage
- Parent of every other `raw_rafiki` table via `merchant_id`.
- Cross-source: no direct customer link (merchant users / payouts carry `canonical_cid`).
