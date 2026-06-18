# raw_core_transfers.transfer_legs

**Source system:** internal core product DB (Postgres)
**Grain:** one row per leg of a transfer (funding, fx, payout)
**Approx rows (demo scale):** ~9,000,000
**Loaded by:** warehouse/generators/gen_raw_core_transfers.py

## Business definition
The internal sub-movements that make up a transfer. Each transfer has three legs in sequence: `funding` (debit the sender), `fx` (currency conversion), and `payout` (credit the recipient). Used to trace money flow and partner attribution per stage.

## Known data-quality quirks
- Always three legs per transfer, `sequence_no` 1-3 in funding -> fx -> payout order.
- `status` is derived from the parent transfer status; a FAILED transfer fails only on the payout leg while earlier legs read SUCCESS.
- `finished_at` is null when the leg status is PENDING.
- `leg_id` is a generated surrogate serial assigned at load time.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| leg_id | bigint | no | Primary key (surrogate serial) |
| transfer_id | uuid | no | -> transfers.transfer_id |
| leg_type | text | no | funding / fx / payout |
| sequence_no | integer | no | Leg order (1-3) |
| from_currency | text | no | Source currency of the leg |
| to_currency | text | no | Target currency of the leg |
| amount | numeric(18,2) | no | Leg amount (send for funding/fx, receive for payout) |
| partner | text | no | Partner handling the leg |
| partner_reference | text | no | Partner-side reference id |
| status | text | no | SUCCESS / PENDING / FAILED |
| started_at | timestamptz | no | Leg start time |
| finished_at | timestamptz | no | Leg finish time (null if PENDING) |

## Joins / lineage
- `transfer_id` -> transfers.transfer_id (child table).
