# raw_core_transfers.recipients

**Source system:** internal core product DB (Postgres)
**Grain:** one row per beneficiary (recipient) owned by a sending customer
**Approx rows (demo scale):** ~120,000
**Loaded by:** warehouse/generators/gen_raw_core_transfers.py

## Business definition
The beneficiaries that customers send money to. Each recipient belongs to a sending customer and has a receive country/currency, relationship, and PII contact details. This is the modern, canonical recipient table (saved_recipients is its legacy predecessor).

## Known data-quality quirks
- `email` is sparse (~55% null) and dirtied; recipients rarely have email.
- `date_of_birth` is very sparse (~70% null) and stored as an ISO string-derived value.
- `phone` is dirtied (inconsistent format).
- `full_name` is a denormalized concatenation of first/last (redundant PII).
- Soft delete: `is_deleted` (~5% true); `is_active` true ~92% of the time.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| recipient_id | bigint | no | Primary key |
| recipient_uuid | uuid | no | `det_uuid(("recipient", idx))` |
| customer_id | bigint | no | Owning sender -> customers.customer_id |
| first_name | text | yes | Recipient first name |
| last_name | text | yes | Recipient last name |
| full_name | text | yes | Denormalized full name |
| receive_country | text | no | Credit country |
| receive_currency | text | no | Credit currency |
| relationship | text | no | family / friend / self / business |
| phone | text | yes | Recipient phone (dirty) |
| email | text | yes | Recipient email (~55% null) |
| date_of_birth | date | yes | Recipient DOB (~70% null) |
| is_active | boolean | no | Active flag (~92% true) |
| is_deleted | boolean | no | Soft-delete flag (~5% true) |
| created_at | timestamptz | no | Creation time |
| updated_at | timestamptz | no | Last update |

## Joins / lineage
- `customer_id` -> customers.customer_id (owning sender).
- `recipient_id` is referenced by transfers.recipient_id, recipient_payout_methods.recipient_id, and saved_recipients.migrated_recipient_id.
