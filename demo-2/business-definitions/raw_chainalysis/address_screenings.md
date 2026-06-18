# raw_chainalysis.address_screenings

**Source system:** Chainalysis (crypto wallet risk screening — Address Screening / KYT API)
**Grain:** one row per address screening request (one screened wallet address)
**Approx rows (demo scale):** ~24,000 (~12% of customers touched crypto, ×~1.3 wallets, plus ~15,000 pure counterparty wallets)
**Loaded by:** warehouse/generators/gen_raw_chainalysis.py

## Business definition
A Chainalysis screening of a single crypto wallet address. Because NALA/Rafiki settle in stablecoins, deposit and withdrawal wallet addresses are screened for exposure to sanctioned, darknet, scam and other risk categories. `risk` (Low/Medium/High/Severe) and `cluster_category` drive whether the wallet is blocked; `is_sanctioned` flags direct sanctions hits. Rows split between NALA customers and pure counterparty wallets.

## Known data-quality quirks
- `nala_customer_code` is sparse — NULL for all counterparty wallets (a large share of rows).
- Wallet `address` format depends on `network` (0x… for EVM chains, T… for Tron) — treated as PII though pseudonymous.
- `risk` skews safe: ~90% Low/Medium, ~8% High, ~2% Severe; `is_sanctioned` only on a subset of Severe.
- `risk_reason` ~40% null (free text); `status` ~96% COMPLETE with a small PENDING/ERROR tail.
- `requested_at`/`updated_at` are ISO-8601 strings (text; vendor camelCase `updatedAt`).
- `raw_response` is a camelCase vendor jsonb payload.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | PK, "scr_<uuid>" |
| address | text | yes | crypto wallet address (pseudonymous, treated as PII) |
| asset | text | no | USDC / USDT / PYUSD / ETH / TRX / BTC |
| network | text | no | ethereum / tron / bitcoin / polygon / base |
| nala_customer_code | text | no | CUS_... (join key; NULL for counterparties) |
| direction | text | no | DEPOSIT / WITHDRAWAL (relative to NALA) |
| risk | text | no | Low / Medium / High / Severe (Chainalysis rating) |
| risk_reason | text | no | free-text reason (~40% null) |
| cluster_name | text | no | attributed entity/cluster (Binance, Lazarus Group, ...) |
| cluster_category | text | no | exchange / sanctioned entity / darknet market / scam / mixing / p2p |
| is_sanctioned | boolean | no | direct sanctions-hit flag |
| status | text | no | COMPLETE / PENDING / ERROR |
| requested_at | text | no | ISO-8601 string |
| updated_at | text | no | ISO-8601 string (vendor updatedAt) |
| raw_response | jsonb | yes | full vendor payload (contains the address) |

## Joins / lineage
- `nala_customer_code` -> customer_master.
- `id` <- raw_chainalysis.screening_alerts.screening_id, exposure.screening_id.
- `id` matched by raw_compliance.case_management.source_ref when `source='chainalysis'`.
