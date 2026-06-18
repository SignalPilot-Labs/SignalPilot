# raw_ledger.reconciliation_runs

**Source system:** internal core ledger service (recon job)
**Grain:** one row per reconciliation run (recon_type x as_of_date)
**Approx rows (demo scale):** ~360 (test)
**Loaded by:** warehouse/generators/gen_raw_ledger.py

## Business definition
Each run compares the internal ledger to an external source of truth (Fireblocks custody, Circle, bank, or internal cross-check) as of a date. Records how many breaks were found and their total absolute amount. Treasury/ops review OPEN breaks daily.

## Known data-quality quirks
- BANK and INTERNAL recon types don't run every day (sparse).
- ~4% of runs are RUNNING or FAILED (no completion ts / no breaks recorded).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| run_id | bigint | no | PK |
| run_uuid | text | no | UUID |
| recon_type | text | no | FIREBLOCKS / CIRCLE / BANK / INTERNAL |
| as_of_date | date | no | Reconciliation date |
| started_at | timestamptz | no | Run start |
| completed_at | timestamptz | no | Run end (null if not completed) |
| status | text | no | COMPLETED / RUNNING / FAILED |
| total_breaks | integer | no | Count of breaks |
| total_break_amount | numeric(20,4) | no | Sum of abs(break_amount) |
| run_by | text | no | Job / actor |
| metadata | jsonb | no | Free-form |

## Joins / lineage
- `run_id` <- raw_ledger.reconciliation_breaks.run_id.
- `recon_type` conceptually maps to raw_fireblocks / raw_circle (no FK).
