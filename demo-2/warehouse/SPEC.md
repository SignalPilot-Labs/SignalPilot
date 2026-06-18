# NALA Warehouse Build — Subagent SPEC (single source of truth)

You are building a slice of a deliberately **messy, enterprise-grade** Postgres
warehouse that mimics the real data estate of **NALA** (cross-border remittance
fintech: consumer app + Rafiki B2B payments API). Read `company-profile.md` in
`demo-2/` for business context. Read this whole file before writing anything.

Everything connects to an isolated Postgres already running:
`host=localhost port=5602 db=nala_warehouse user=nala password=nala_dev_only`.

## Golden rules

1. **Import the shared contract.** Every generator does `from common import *`
   (file: `warehouse/generators/common.py`). NEVER hardcode the connection, row
   counts, currency lists, or customer identities. Use `connect()`, `bulk_copy()`,
   `apply_ddl_file()`, `truncate()`, `customer_master()`, `random_customer()`,
   `rng()`, `rand_datetime()`, `det_uuid()`, the messiness helpers
   (`maybe_null`, `dirty_email`, `dirty_phone`, `ts_iso`, `ts_isoz`,
   `ts_epoch_ms`, `ts_epoch_s`), and reference data (`SEND_CURRENCIES`,
   `SEND_COUNTRIES`, `RECEIVE_MARKETS`, `RECEIVE_COUNTRIES`, `STABLECOINS`,
   `USD_FX`, `PARTNERS`, `DEVICE_PLATFORMS`, `APP_VERSIONS`, `N`).
2. **Scale-aware.** Size big fact tables off `N[...]` (e.g. `N["transfers"]`).
   Dimensions/lookups: pick sensible fixed sizes. Your generator MUST run end to
   end at `NALA_SCALE=test` (tiny) before you report done.
3. **Cross-source join keys.** The canonical customer population lives in
   `common.customer_master()` (indices `0 .. N["customers"]-1`). Reference the
   SAME customer across systems so demos can join. Use the representation natural
   to your system: integer `cid`, `code` (`CUS_00000123`), `uuid`, or the
   customer's `email`/`phone` (run these through `dirty_email`/`dirty_phone` so
   identity resolution is realistically hard). `transfer_id` should be a UUID
   produced via `det_uuid(("transfer", i))` for the core transfers table; other
   systems that reference a transfer reuse that. (Only the core_transfers agent
   owns the transfer id space — others reference a random subset.)
4. **Messy like real enterprises.** Apply liberally, but realistically:
   - Inconsistent naming ACROSS source systems (a Stripe table may use
     `created`, M-Pesa `TransactionDate`, internal `created_at`). WITHIN one
     vendor's tables, stay consistent with that vendor's real API style.
   - Timestamp format drift between systems (ISO, ISO-Z, epoch ms, epoch s,
     naive vs tz). Use the `ts_*` helpers.
   - Nullable/sparse columns (`maybe_null`), legacy/deprecated columns kept
     around, `_v1`/`_old`/`_legacy` duplicate tables, soft-delete flags
     (`is_deleted`, `deleted_at`), free-text status with legacy values, JSON/JSONB
     blob columns holding semi-structured vendor payloads, denormalized snapshots.
   - Some FKs not enforced at DB level (that's realistic) — DO NOT add cross-schema
     FOREIGN KEY constraints. Primary keys are fine within a table.
5. **PII, enterprise style.** This is a financial company. Include PII where a
   real system would have it: names, emails, phones, DOB, addresses, national id
   / passport numbers, bank account / IBAN / card last4 + BIN, mobile-money MSISDN,
   IP addresses, device ids, crypto wallet addresses. Tag every PII column in its
   business-definition doc (see doc format). Do NOT encrypt/mask — this is fake
   data, but treat column design as if governed (e.g. store card `last4` + `bin`,
   never full PAN; store `national_id_hash` alongside `national_id` in some
   systems to mimic partial governance).
6. **Real-world services & values.** Use real vendor/product names and realistic
   enums (M-PESA, Flutterwave, Stripe, Onfido, Segment, Braze, Zendesk, NetSuite,
   Fireblocks, Circle, MTN MoMo, GCash, bKash, etc.). See `PARTNERS` and
   `RECEIVE_MARKETS` for the canonical lists.
7. **Idempotent.** Generator `main()` order: ensure schema → `apply_ddl_file()` →
   `truncate()` your tables → load. Re-running fully rebuilds your slice.

## Deliverables per domain (4 things)

1. **DDL** → `warehouse/sql/ddl/<schema>.sql`
   - One file per schema you own. Starts with `CREATE SCHEMA IF NOT EXISTS ...;`
     then `CREATE TABLE IF NOT EXISTS <schema>.<table> (...);` for every table.
   - Use real Postgres types (`bigint`, `numeric(18,2)`, `timestamptz`, `text`,
     `jsonb`, `boolean`, `date`, `inet`). Reflect the messiness (e.g. a column
     that holds epoch ms is `bigint`; one holding ISO string is `text`).
2. **Generator** → `warehouse/generators/gen_<schema>.py`
   - `from common import *`. Implements `def main(conn): ...` plus
     `if __name__ == "__main__": c = connect(); main(c); c.close()`.
   - Loads ALL tables you own using `bulk_copy`. Big tables stream rows from a
     generator function (don't build giant lists in memory).
3. **Business-definition docs** → `business-definitions/<schema>/<table>.md`
   - One file PER table. Use the doc template at the bottom of this file.
4. **dbt** → in `demo-2/nala_dbt/`
   - Add your source tables to a sources file:
     `models/staging/<schema>/_<schema>__sources.yml` (define the `<schema>`
     source pointing at the real schema/tables, with table + column descriptions
     for the important columns, and `loaded_at_field` where sensible).
   - Write staging models ONLY for your KEY tables (~5–7 per domain), file
     `models/staging/<schema>/stg_<schema>__<entity>.sql`. Staging models:
     `select` from `{{ source('<schema>','<table>') }}`, rename to snake_case,
     cast types, coalesce the messy timestamps into one clean `*_at timestamptz`,
     standardize status enums. Materialized as views (project default). Keep them
     1:1 with the source (no joins in staging).
   - Do NOT touch `dbt_project.yml` (the orchestrator owns it). Do NOT write
     intermediate/marts models (Wave 2 owns those).

## dbt naming conventions

- Sources: the schema name (e.g. `raw_stripe`), table = real table name.
- Staging: `stg_<schema-without-raw_>__<entity>` e.g. `stg_stripe__charges`.
- Use `{{ source(...) }}` only in staging; downstream uses `{{ ref(...) }}`.
- snake_case all output columns. Surrogate-key style ids end in `_id`.

## Business-definition doc template

```markdown
# <schema>.<table>

**Source system:** <real vendor/system, e.g. Stripe / internal core / M-PESA Daraja>
**Grain:** <one row per ...>
**Approx rows (demo scale):** <n>
**Loaded by:** warehouse/generators/gen_<schema>.py

## Business definition
<2–4 sentences: what this table represents in NALA's business and how it's used.>

## Known data-quality quirks
- <e.g. created_at stored as epoch ms; status has legacy value 'PENDING_OLD'; ~8% null email>

## Columns
| column | type | PII | description |
|--------|------|-----|-------------|
| ... | ... | yes/no | ... |

## Joins / lineage
- Joins to `<schema.table>` on `<key>` (note if the key is dirty/needs cleaning).
```

---

# TABLE INVENTORY BY DOMAIN

Each agent owns the schemas + tables listed under its number. Hit the table
counts roughly; add a sensible extra table or two if the business needs it.

### Domain 1 — Core Transfers (`raw_core_transfers`)  [the heart of the product]
customers (PII-heavy sender accounts; ref customer_master), customer_addresses,
customer_devices, customer_kyc_status, recipients (beneficiary PII),
recipient_payout_methods (MSISDN / bank acct / IBAN — PII), saved_recipients
(LEGACY near-duplicate of recipients, messy), transfers (FACT: `N["transfers"]`
rows; transfer_id via det_uuid(("transfer",i)); send+receive currency/country,
amounts, fees, fx_rate, status, rail, partner), transfer_legs,
transfer_status_history, transfer_fees, quotes, fx_quotes, payout_attempts,
promo_redemptions, referrals, referral_codes, corridors (lookup), 
cancellation_reasons (lookup). PII: yes.

### Domain 2 — Rafiki B2B (`raw_rafiki`)
merchants, merchant_users (PII), merchant_api_keys (key prefix + hash, PII-ish),
merchant_kyb, collections, payouts (B2B payouts), settlements, settlement_lines,
webhooks, webhook_deliveries, invoices, invoice_line_items, balances,
balance_transactions, fx_locks, rate_cards. Stablecoin settlement (USDC/USDT/PYUSD).

### Domain 3 — Ledger & Crypto Treasury (`raw_ledger`, `raw_fireblocks`, `raw_circle`)
raw_ledger: accounts, account_types(lookup), journal_entries,
journal_lines (FACT: `N["ledger_lines"]`, double-entry — debits=credits per entry),
wallets, wallet_transactions, balance_snapshots, reconciliation_runs,
reconciliation_breaks.
raw_fireblocks: vault_accounts, vault_transactions, supported_assets(lookup).
raw_circle: usdc_wallets, usdc_transfers, usdc_payments, chargebacks.
PII: crypto wallet addresses.

### Domain 4 — FX & Pricing (`raw_fx`, `raw_openexchange`)
raw_fx: fx_rates (time series, hourly per currency pair — sizeable),
fx_rate_snapshots, pricing_margins, corridor_pricing, rate_providers(lookup),
fx_pnl, fx_hedges.
raw_openexchange: latest_rates, historical_rates, currencies(lookup).

### Domain 5 — Mobile-Money Rails (`raw_mpesa`, `raw_flutterwave`)
raw_mpesa (Safaricom Daraja API naming — CamelCase fields, e.g. `TransactionID`,
`MSISDN`, `TransAmount`): stk_push_requests, c2b_payments, b2c_requests,
callbacks, transaction_status_queries, account_balance_queries, statements.
raw_flutterwave: transfers, transfer_retries, balances, banks(lookup),
beneficiaries (PII: bank acct), webhooks, settlements. PII: MSISDN, bank acct.

### Domain 6 — Funding & Banking Rails (`raw_stripe`, `raw_plaid`, `raw_marqeta`)
raw_stripe (Stripe API naming: `id` like `ch_...`, `created` epoch s, amounts in
minor units): customers, payment_intents, charges, refunds, disputes, payouts,
balance_transactions, payment_methods (card brand/last4/bin — PII), events.
raw_plaid: items, accounts, auth_numbers (acct/routing — PII), transactions,
identity_data (PII).
raw_marqeta: cardholders (PII), cards (last4/pan_token — PII), card_transactions,
funding_sources.

### Domain 7 — Identity, KYC & Compliance (`raw_onfido`, `raw_complyadvantage`, `raw_chainalysis`, `raw_compliance`)
raw_onfido: applicants (PII: name/dob/address), checks, reports, documents
(doc type/number — PII), facial_similarity_reports, watchlist_reports.
raw_complyadvantage: searches, search_hits, monitors, monitor_alerts.
raw_chainalysis: address_screenings (wallet address — PII), screening_alerts,
exposure.
raw_compliance (internal): sars (suspicious activity reports), case_management,
risk_scores, sanctions_list(lookup). PII: heavy.

### Domain 8 — Growth & Product Analytics (`raw_segment`, `raw_amplitude`, `raw_appsflyer`, `raw_app_store`)
raw_segment: tracks (FACT events: ~`N["events"]`; jsonb `properties`; anonymous_id
+ user_id), identifies, pages, screens, groups.
raw_amplitude: events, user_properties, cohorts.
raw_appsflyer: installs, in_app_events, attributions, media_sources(lookup).
raw_app_store: apple_downloads, apple_reviews, google_play_installs,
google_play_reviews. PII: ip, device id, idfa/gaid.

### Domain 9 — Marketing, CRM & Support (`raw_braze`, `raw_google_ads`, `raw_meta_ads`, `raw_zendesk`, `raw_intercom`)
raw_braze: campaigns, canvases, messages_sent, custom_events, segments.
raw_google_ads: campaigns, ad_groups, ad_performance_daily.
raw_meta_ads: campaigns, ad_sets, ad_insights_daily.
raw_zendesk: tickets, ticket_comments, users (PII: email), satisfaction_ratings.
raw_intercom: conversations, conversation_parts.

### Domain 10 — Comms, Finance & HR (`raw_twilio`, `raw_sendgrid`, `raw_netsuite`, `raw_workday`)
raw_twilio: messages (to-number — PII), phone_lookups.
raw_sendgrid: messages (to-email — PII), events (open/click/bounce).
raw_netsuite: gl_accounts, gl_transactions, vendors, vendor_bills,
departments(lookup), subsidiaries(lookup).
raw_workday (HR): employees (PII: name/email/salary/ssn-style id), departments,
compensation, time_off.

---

## What to hand back (your final message)

Return a concise structured report:
- schemas + table names created (with row counts at test scale)
- list of staging models + source yml files written
- KEY join keys you exposed for cross-source demos
- any deviations from the spec or known issues for the integrator to fix
Do NOT print file contents. Keep it tight.
