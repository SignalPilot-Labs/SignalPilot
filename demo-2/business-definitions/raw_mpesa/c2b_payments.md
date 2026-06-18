# raw_mpesa.c2b_payments

**Source system:** Safaricom M-PESA Daraja API (C2B confirmation — Paybill / Buy Goods)
**Grain:** one row per customer-to-business payment confirmation
**Approx rows (demo scale):** ~216k
**Loaded by:** warehouse/generators/gen_raw_mpesa.py

## Business definition
C2B confirmation events Daraja POSTs when a customer pays NALA's Paybill/Till
directly (manual funding, off-app). One row per confirmed inbound payment.

## Known data-quality quirks
- `TransTime` is `yyyyMMddHHmmss` string; `ingested_at` is epoch **milliseconds** (bigint) — two different time encodings in one table.
- Daraja splits the payer name into `FirstName`/`MiddleName`/`LastName`; `MiddleName` ~50% NULL, `LastName` ~40% NULL.
- `MSISDN` may be masked by Daraja depending on Org settings; dirtied via `dirty_phone`.
- `BillRefNumber` (our customer code) ~20% NULL; `InvoiceNumber`/`ThirdPartyTransID` very sparse.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| TransID | text | no | PK; M-PESA receipt |
| TransactionType | text | no | "Pay Bill" / "Buy Goods" |
| TransTime | text | no | `yyyyMMddHHmmss` string |
| TransAmount | numeric(18,2) | no | amount paid |
| BusinessShortCode | text | no | NALA shortcode |
| BillRefNumber | text | no | our customer code, sparse |
| InvoiceNumber / ThirdPartyTransID | text | no | sparse references |
| OrgAccountBalance | numeric(18,2) | no | shortcode balance after txn |
| MSISDN | text | yes | payer mobile number |
| FirstName / MiddleName / LastName | text | yes | payer name parts (sparse) |
| nala_transfer_id | uuid | no | soft ref to core transfers |
| nala_customer_code | text | no | soft ref `CUS_########` |
| currency | text | no | KES / TZS |
| ingested_at | bigint | no | epoch **ms** ingest time |
| raw_payload | jsonb | no | vendor blob |

## Joins / lineage
- `nala_transfer_id` → `raw_core_transfers.transfers` (soft).
- `nala_customer_code` → `customer_master()` code.
