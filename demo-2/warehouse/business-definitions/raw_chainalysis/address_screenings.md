# raw_chainalysis.address_screenings

**Source system:** Chainalysis (crypto wallet risk screening / KYT)
**Grain:** one row per address screening request
**Approx rows (demo scale):** ~22k (customer wallets + counterparty wallets)
**Loaded by:** warehouse/generators/gen_raw_chainalysis.py

## Business definition
NALA/Rafiki settle in stablecoins (USDC/USDT/PYUSD), so every deposit/withdrawal
wallet address is screened by Chainalysis for exposure to sanctioned, darknet, scam
and other risk categories. Each row is one screening of one address.

## Known data-quality quirks
- `address` is a crypto wallet (ETH 0x..., TRON T...) — pseudonymous PII.
- `nala_customer_code` is sparse: ~55% of rows are pure counterparty wallets (null).
- Timestamps are ISO-8601 strings with Z; the vendor field is `updatedAt`.
- `raw_response` is the full vendor camelCase jsonb payload.

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| id | text | no | screening id ("scr_<uuid>"), PK |
| address | text | yes | crypto wallet address |
| asset | text | no | USDC / USDT / PYUSD / ETH / TRX / BTC |
| network | text | no | ethereum / tron / polygon / base / bitcoin |
| nala_customer_code | text | no | CUS_00000123 (join key; ~55% null = counterparty) |
| direction | text | no | DEPOSIT / WITHDRAWAL relative to NALA |
| risk | text | no | Low / Medium / High / Severe |
| risk_reason | text | no | free-text reason (~40% null) |
| cluster_name | text | no | attributed entity/cluster |
| cluster_category | text | no | exchange / sanctioned entity / darknet market / scam / ... |
| is_sanctioned | boolean | no | sanctioned-cluster flag |
| status | text | no | COMPLETE / PENDING / ERROR |
| requested_at | text | no | ISO-8601 string (Z) |
| updated_at | text | no | ISO-8601 string (Z) |
| raw_response | jsonb | no | full vendor payload |

## Joins / lineage
- Joins to NALA core customers on `nala_customer_code = customers.code` (sparse).
- 1:1/1:N to `raw_chainalysis.screening_alerts` and `raw_chainalysis.exposure`
  on `id = screening_id`.
