# raw_openexchange.currencies

**Source system:** Open Exchange Rates API (openexchangerates.org) /currencies.json
**Grain:** one row per ISO currency code
**Approx rows (demo scale):** ~19
**Loaded by:** warehouse/generators/gen_raw_openexchange.py

## Business definition
Vendor lookup mapping ISO currency code to display name, mirroring Open Exchange
Rates' /currencies.json endpoint. Extended with the stablecoins NALA tracks.
Used to label rates in `latest_rates` / `historical_rates`.

## Known data-quality quirks
- Stablecoins (USDC/USDT/PYUSD) are vendor extensions, flagged `is_crypto=true`.
- `decimals` reflects minor-unit precision (0 for UGX/TZS/RWF/XOF/XAF, 6 for stablecoins, else 2).

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| code | text | no | PK, ISO-4217 (or crypto) code. |
| name | text | no | Display name. |
| is_crypto | boolean | no | True for stablecoins. |
| decimals | integer | no | Minor-unit precision. |

## Joins / lineage
- `code` joins `raw_openexchange.latest_rates.currency` and `historical_rates.currency`.
- Overlaps `raw_fx.fx_rates.quote_currency`.
- PII: none.
