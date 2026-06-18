# raw_core_transfers.transfer_status_history

**Source system:** internal core product DB (Postgres)
**Grain:** one row per status transition of a transfer
**Approx rows (demo scale):** ~10,500,000
**Loaded by:** warehouse/generators/gen_raw_core_transfers.py

## Business definition
The audit trail of state changes for each transfer. A transfer emits a chain of events (e.g. CREATED -> FUNDED -> PROCESSING -> COMPLETED), each row capturing the prior and new status, who changed it, and when.

## Known data-quality quirks
- `changed_at` is an ISO-Z **string** (text), not a timestamptz — timezone drift, requires casting.
- `from_status` is NULL on the first event in a chain (the CREATED row).
- Chain length varies by outcome (3-4 events typical; CANCELLED is shortest).
- `changed_by` is free text: `system`, `partner_webhook`, or an agent email (`ops@nala.com`).
- `note` is almost always null.
- `status_event_id` is a generated surrogate serial assigned at load time.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| status_event_id | bigint | no | Primary key (surrogate serial) |
| transfer_id | uuid | no | -> transfers.transfer_id |
| from_status | text | no | Prior status (null on first event) |
| to_status | text | no | New status |
| changed_at | text | no | ISO-Z string timestamp (not tz) |
| changed_by | text | yes | system / partner_webhook / agent email |
| note | text | no | Free-text note (mostly null) |

## Joins / lineage
- `transfer_id` -> transfers.transfer_id (child table).
