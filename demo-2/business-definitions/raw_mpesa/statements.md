# raw_mpesa.statements

**Source system:** Safaricom M-PESA Daraja API / M-PESA Org portal (reconciliation statement export)
**Grain:** one row per ledger line on a NALA M-PESA shortcode
**Approx rows (demo scale):** ~324k
**Loaded by:** warehouse/generators/gen_raw_mpesa.py

## Business definition
Daily reconciliation statement lines for NALA's M-PESA shortcodes — the
authoritative debit/credit ledger of the float. Each payout (B2C) appears as a
`Withdrawn`, each collection (C2B) as a `Paidin`, with a running `Balance`.

## Known data-quality quirks
- `CompletionTime`/`InitiationTime` use `yyyy-MM-dd HH:mm:ss` (a THIRD M-PESA date format — distinct from Daraja's `yyyyMMddHHmmss` and B2C's `dd.MM.yyyy`).
- Daraja's odd capitalisation: `Paidin` (credit) and `Withdrawn` (debit) — exactly one is populated per row, the other NULL.
- `OtherPartyInfo` is masked counterparty text (PII), ~30% NULL.
- Soft-delete via `is_deleted` (~1%); `LinkedTransactionID`/`AccountNo` sparse.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| statement_line_id | bigint | no | PK (synthetic) |
| BusinessShortCode | text | no | NALA shortcode |
| ReceiptNo | text | no | M-PESA receipt |
| CompletionTime / InitiationTime | text | no | `yyyy-MM-dd HH:mm:ss` strings |
| TransactionType | text | no | "Business Payment to Customer" / "Pay Bill" / "Buy Goods" |
| Paidin | numeric(18,2) | no | credit (NULL if debit) |
| Withdrawn | numeric(18,2) | no | debit (NULL if credit) |
| Balance | numeric(18,2) | no | running float balance |
| BalanceConfirmed | boolean | no | reconciliation confirmation flag |
| ReasonType | text | no | free text |
| OtherPartyInfo | text | yes | masked counterparty |
| LinkedTransactionID / AccountNo | text | no | sparse references |
| statement_date | date | no | statement day |
| currency | text | no | KES / TZS |
| is_deleted | boolean | no | soft-delete flag |
| raw_payload | jsonb | no | vendor blob |

## Joins / lineage
- `ReceiptNo` aligns to `raw_mpesa.b2c_requests.TransactionReceipt` / `c2b_payments.TransID` (dirty; not all receipts overlap).
- Aligns to `account_balance_queries` by shortcode + date.
