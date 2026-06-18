# raw_netsuite.vendors

**Source system:** Oracle NetSuite — Vendor record (AP master)
**Grain:** one row per vendor
**Approx rows (demo scale):** 20
**Loaded by:** warehouse/generators/gen_raw_netsuite.py

## Business definition
NALA's accounts-payable vendor master: infrastructure (Twilio, AWS, Snowflake), compliance (Onfido, ComplyAdvantage, Chainalysis), banking/payout partners (Flutterwave, Stripe, Plaid, Fireblocks, Circle), marketing and professional services. Drives spend-by-vendor and AP analytics.

## Known data-quality quirks
- `email`, `phone`, `tax_id` are sparse (AP contact data not always captured).
- `entityid` is NetSuite's display id ("V5001 Twilio Inc"), distinct from numeric `vendor_id`.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| vendor_id | bigint | no | NetSuite internalId (PK) |
| entityid | text | no | display id ("V5001 Twilio Inc") |
| company_name | text | no | vendor company name |
| category | text | no | Infrastructure/Compliance/Banking/Marketing/… |
| email | text | yes | AP contact email (sparse) |
| phone | text | yes | AP contact phone (sparse) |
| subsidiary_id | bigint | no | primary subsidiary |
| currency | text | no | default bill currency |
| tax_id | text | yes | VAT/EIN (sparse) |
| terms | text | no | payment terms (Net 30…) |
| is_1099_eligible | boolean | no | 1099 reporting flag |
| is_inactive | boolean | no | inactive flag |
| created_at | timestamptz | no | vendor creation |

## Joins / lineage
- Referenced by `vendor_bills.vendor_id`. `subsidiary_id` -> subsidiaries.
