# NALA Warehouse — Business Definitions Index

One doc per table, grouped by source-system domain. Each table doc lists grain, approx demo-scale rows, the deliberate data-quality quirks, a full column dictionary with PII flags, and join/lineage keys. See `../warehouse/SPEC.md` for conventions and `../company-profile.md` for business context.


**157 tables across 29 source schemas · 223 PII-tagged columns**


## Core Transfers (consumer product)


### `raw_core_transfers` (19 tables)

| table | grain | PII cols | doc |
|---|---|---|---|
| `cancellation_reasons` | one row per cancellation reason code | 0 | [doc](raw_core_transfers/cancellation_reasons.md) |
| `corridors` | one row per supported send-currency x receive-market corridor | 0 | [doc](raw_core_transfers/corridors.md) |
| `customer_addresses` | one row per customer address (a customer may have 1-2) | 4 | [doc](raw_core_transfers/customer_addresses.md) |
| `customer_devices` | one row per device registered to a customer (1-3 per customer) | 3 | [doc](raw_core_transfers/customer_devices.md) |
| `customer_kyc_status` | one row per customer KYC decision (one current row per customer at demo scale) | 1 | [doc](raw_core_transfers/customer_kyc_status.md) |
| `customers` | one row per sending customer (canonical cid) | 7 | [doc](raw_core_transfers/customers.md) |
| `fx_quotes` | one row per FX rate lock backing a quote | 0 | [doc](raw_core_transfers/fx_quotes.md) |
| `payout_attempts` | one row per payout attempt against a transfer (a transfer may retry) | 2 | [doc](raw_core_transfers/payout_attempts.md) |
| `promo_redemptions` | one row per promo code redeemed on a transfer | 0 | [doc](raw_core_transfers/promo_redemptions.md) |
| `quotes` | one row per pricing quote requested by a customer | 0 | [doc](raw_core_transfers/quotes.md) |
| `recipient_payout_methods` | one row per payout method attached to a recipient (1-2 per recipient) | 4 | [doc](raw_core_transfers/recipient_payout_methods.md) |
| `recipients` | one row per beneficiary (recipient) owned by a sending customer | 6 | [doc](raw_core_transfers/recipients.md) |
| `referral_codes` | one row per shareable referral code owned by a customer | 0 | [doc](raw_core_transfers/referral_codes.md) |
| `referrals` | one row per referral (a referrer inviting a referee) | 0 | [doc](raw_core_transfers/referrals.md) |
| `saved_recipients` | one row per legacy saved beneficiary (only ~40% of recipients have one) | 3 | [doc](raw_core_transfers/saved_recipients.md) |
| `transfer_fees` | one row per fee component of a transfer | 0 | [doc](raw_core_transfers/transfer_fees.md) |
| `transfer_legs` | one row per leg of a transfer (funding, fx, payout) | 0 | [doc](raw_core_transfers/transfer_legs.md) |
| `transfer_status_history` | one row per status transition of a transfer | 1 | [doc](raw_core_transfers/transfer_status_history.md) |
| `transfers` | one row per money transfer (send) initiated by a customer | 1 | [doc](raw_core_transfers/transfers.md) |

## Rafiki B2B payments


### `raw_rafiki` (16 tables)

| table | grain | PII cols | doc |
|---|---|---|---|
| `balance_transactions` | one row per balance movement | 0 | [doc](raw_rafiki/balance_transactions.md) |
| `balances` | one row per merchant per currency (current snapshot) | 0 | [doc](raw_rafiki/balances.md) |
| `collections` | one row per inbound stablecoin collection | 1 | [doc](raw_rafiki/collections.md) |
| `fx_locks` | one row per locked FX quote | 0 | [doc](raw_rafiki/fx_locks.md) |
| `invoice_line_items` | one row per line on an invoice | 0 | [doc](raw_rafiki/invoice_line_items.md) |
| `invoices` | one row per merchant per billing month | 0 | [doc](raw_rafiki/invoices.md) |
| `merchant_api_keys` | one row per issued API key | 2 | [doc](raw_rafiki/merchant_api_keys.md) |
| `merchant_kyb` | one row per merchant KYB case | 4 | [doc](raw_rafiki/merchant_kyb.md) |
| `merchant_users` | one row per user with login access to a merchant account | 3 | [doc](raw_rafiki/merchant_users.md) |
| `merchants` | one row per onboarded B2B merchant | 1 | [doc](raw_rafiki/merchants.md) |
| `payouts` | one row per outbound B2B payout | 2 | [doc](raw_rafiki/payouts.md) |
| `rate_cards` | one row per merchant pricing version (effective-date range) | 0 | [doc](raw_rafiki/rate_cards.md) |
| `settlement_lines` | one row per line within a settlement | 0 | [doc](raw_rafiki/settlement_lines.md) |
| `settlements` | one row per merchant per settlement day | 0 | [doc](raw_rafiki/settlements.md) |
| `webhook_deliveries` | one row per webhook delivery attempt | 0 | [doc](raw_rafiki/webhook_deliveries.md) |
| `webhooks` | one row per configured webhook endpoint | 1 | [doc](raw_rafiki/webhooks.md) |

## Ledger & Crypto Treasury


### `raw_ledger` (9 tables)

| table | grain | PII cols | doc |
|---|---|---|---|
| `account_types` | one row per chart-of-accounts type | 0 | [doc](raw_ledger/account_types.md) |
| `accounts` | one row per general-ledger account (incl. per-customer wallet liability accounts) | 1 | [doc](raw_ledger/accounts.md) |
| `balance_snapshots` | one row per GL account per snapshot date (monthly) | 0 | [doc](raw_ledger/balance_snapshots.md) |
| `journal_entries` | one row per posted accounting event (entry header) | 0 | [doc](raw_ledger/journal_entries.md) |
| `journal_lines` | one row per debit or credit line within a journal entry | 0 | [doc](raw_ledger/journal_lines.md) |
| `reconciliation_breaks` | one row per discrepancy found in a reconciliation run | 0 | [doc](raw_ledger/reconciliation_breaks.md) |
| `reconciliation_runs` | one row per reconciliation run (recon_type x as_of_date) | 0 | [doc](raw_ledger/reconciliation_runs.md) |
| `wallet_transactions` | one row per credit/debit hitting a wallet balance | 0 | [doc](raw_ledger/wallet_transactions.md) |
| `wallets` | one row per balance-holding wallet (customer or treasury) | 2 | [doc](raw_ledger/wallets.md) |

### `raw_fireblocks` (3 tables)

| table | grain | PII cols | doc |
|---|---|---|---|
| `supported_assets` | one row per asset enabled in the Fireblocks workspace | 0 | [doc](raw_fireblocks/supported_assets.md) |
| `vault_accounts` | one row per Fireblocks vault account | 2 | [doc](raw_fireblocks/vault_accounts.md) |
| `vault_transactions` | one row per Fireblocks transaction (transfer/mint/burn) | 4 | [doc](raw_fireblocks/vault_transactions.md) |

### `raw_circle` (4 tables)

| table | grain | PII cols | doc |
|---|---|---|---|
| `chargebacks` | one row per chargeback/dispute against a card payment | 0 | [doc](raw_circle/chargebacks.md) |
| `usdc_payments` | one row per fiat funding payment (card/ACH/wire/blockchain) or refund | 3 | [doc](raw_circle/usdc_payments.md) |
| `usdc_transfers` | one row per USDC transfer (wallet-to-wallet or on-chain) | 2 | [doc](raw_circle/usdc_transfers.md) |
| `usdc_wallets` | one row per Circle wallet (merchant or end-user) | 2 | [doc](raw_circle/usdc_wallets.md) |

## FX & Pricing


### `raw_fx` (7 tables)

| table | grain | PII cols | doc |
|---|---|---|---|
| `corridor_pricing` | one row per (send currency, receive country, payout method) corridor | 0 | [doc](raw_fx/corridor_pricing.md) |
| `fx_hedges` | one row per hedge position (spot / forward / swap) | 0 | [doc](raw_fx/fx_hedges.md) |
| `fx_pnl` | one row per (currency pair, P&L date) — weekly marks at demo scale | 0 | [doc](raw_fx/fx_pnl.md) |
| `fx_rate_snapshots` | one row per board snapshot (USD-base rate board, every ~6h) | 0 | [doc](raw_fx/fx_rate_snapshots.md) |
| `fx_rates` | one row per (currency pair, timestamp tick) — hourly at demo scale | 0 | [doc](raw_fx/fx_rates.md) |
| `pricing_margins` | one row per (send currency, receive currency, customer segment, effective period) | 0 | [doc](raw_fx/pricing_margins.md) |
| `rate_providers` | one row per upstream rate provider the engine can ingest from | 0 | [doc](raw_fx/rate_providers.md) |

### `raw_openexchange` (3 tables)

| table | grain | PII cols | doc |
|---|---|---|---|
| `currencies` | one row per ISO currency code | 0 | [doc](raw_openexchange/currencies.md) |
| `historical_rates` | one row per (rate_date, currency) — daily USD-base close | 0 | [doc](raw_openexchange/historical_rates.md) |
| `latest_rates` | one row per (fetch, currency); fetches every ~6h over the last ~120 days | 0 | [doc](raw_openexchange/latest_rates.md) |

## Mobile-Money Rails


### `raw_mpesa` (7 tables)

| table | grain | PII cols | doc |
|---|---|---|---|
| `account_balance_queries` | one row per account-balance poll (per shortcode, ~every 3 days) | 0 | [doc](raw_mpesa/account_balance_queries.md) |
| `b2c_requests` | one row per B2C payout request (NALA crediting a recipient's M-PESA wallet) | 2 | [doc](raw_mpesa/b2c_requests.md) |
| `c2b_payments` | one row per customer-to-business payment confirmation | 2 | [doc](raw_mpesa/c2b_payments.md) |
| `callbacks` | one row per async callback received (polymorphic across STK / B2C / status / balance) | 0 | [doc](raw_mpesa/callbacks.md) |
| `statements` | one row per ledger line on a NALA M-PESA shortcode | 1 | [doc](raw_mpesa/statements.md) |
| `stk_push_requests` | one row per STK push (collection) request | 2 | [doc](raw_mpesa/stk_push_requests.md) |
| `transaction_status_queries` | one row per transaction-status query (reconciliation poll) | 1 | [doc](raw_mpesa/transaction_status_queries.md) |

### `raw_flutterwave` (7 tables)

| table | grain | PII cols | doc |
|---|---|---|---|
| `balances` | one row per (currency, snapshot) treasury balance | 0 | [doc](raw_flutterwave/balances.md) |
| `banks` | one row per supported destination bank / mobile-money operator | 0 | [doc](raw_flutterwave/banks.md) |
| `beneficiaries` | one row per saved payout destination | 5 | [doc](raw_flutterwave/beneficiaries.md) |
| `settlements` | one row per settlement batch (per currency, ~weekly) | 0 | [doc](raw_flutterwave/settlements.md) |
| `transfer_retries` | one row per retry attempt of a failed/pending transfer | 0 | [doc](raw_flutterwave/transfer_retries.md) |
| `transfers` | one row per attempted payout to a beneficiary | 3 | [doc](raw_flutterwave/transfers.md) |
| `webhooks` | one row per webhook event received | 0 | [doc](raw_flutterwave/webhooks.md) |

## Funding & Banking Rails


### `raw_stripe` (9 tables)

| table | grain | PII cols | doc |
|---|---|---|---|
| `balance_transactions` | one row per movement on NALA's Stripe balance (charge, refund, payout, fee) | 0 | [doc](raw_stripe/balance_transactions.md) |
| `charges` | one row per charge (a single card capture attempt on a payment intent) | 3 | [doc](raw_stripe/charges.md) |
| `customers` | one row per Stripe Customer object (one NALA app user's card-funding identity) | 3 | [doc](raw_stripe/customers.md) |
| `disputes` | one row per dispute (chargeback) raised against a charge | 0 | [doc](raw_stripe/disputes.md) |
| `events` | one row per Stripe event (webhook notification of an object change) | 0 | [doc](raw_stripe/events.md) |
| `payment_intents` | one row per payment intent (one attempt to collect funds to top up / fund a transfer) | 0 | [doc](raw_stripe/payment_intents.md) |
| `payment_methods` | one row per saved payment method (card / bank / link) on a Stripe customer | 5 | [doc](raw_stripe/payment_methods.md) |
| `payouts` | one row per payout from NALA's Stripe balance to its own bank account | 1 | [doc](raw_stripe/payouts.md) |
| `refunds` | one row per refund issued against a charge | 0 | [doc](raw_stripe/refunds.md) |

### `raw_plaid` (5 tables)

| table | grain | PII cols | doc |
|---|---|---|---|
| `accounts` | one row per bank account exposed under a Plaid Item | 1 | [doc](raw_plaid/accounts.md) |
| `auth_numbers` | one row per account's ACH/wire number set | 3 | [doc](raw_plaid/auth_numbers.md) |
| `identity_data` | one row per linked account's identity record | 8 | [doc](raw_plaid/identity_data.md) |
| `items` | one row per Plaid Item (a NALA user's linked bank-institution connection) | 1 | [doc](raw_plaid/items.md) |
| `transactions` | one row per bank transaction on a linked account | 0 | [doc](raw_plaid/transactions.md) |

### `raw_marqeta` (4 tables)

| table | grain | PII cols | doc |
|---|---|---|---|
| `card_transactions` | one row per card transaction event (auth / clearing / refund / reversal) | 1 | [doc](raw_marqeta/card_transactions.md) |
| `cardholders` | one row per Marqeta user (a NALA cardholder) | 9 | [doc](raw_marqeta/cardholders.md) |
| `cards` | one row per issued card (virtual or physical) | 2 | [doc](raw_marqeta/cards.md) |
| `funding_sources` | one row per funding source (program-level GPA or per-cardholder wallet) | 2 | [doc](raw_marqeta/funding_sources.md) |

## Identity, KYC & Compliance


### `raw_onfido` (6 tables)

| table | grain | PII cols | doc |
|---|---|---|---|
| `applicants` | one row per Onfido applicant (maps 1:1 to a NALA customer) | 9 | [doc](raw_onfido/applicants.md) |
| `checks` | one row per Onfido check (a check groups one or more reports) | 0 | [doc](raw_onfido/checks.md) |
| `documents` | one row per uploaded identity document | 5 | [doc](raw_onfido/documents.md) |
| `facial_similarity_reports` | one row per facial-similarity (selfie vs document) report | 1 | [doc](raw_onfido/facial_similarity_reports.md) |
| `reports` | one row per Onfido report (the unit Onfido actually adjudicates) | 1 | [doc](raw_onfido/reports.md) |
| `watchlist_reports` | one row per watchlist (PEP / sanctions / adverse-media) screening report run inside Onfido | 1 | [doc](raw_onfido/watchlist_reports.md) |

### `raw_complyadvantage` (4 tables)

| table | grain | PII cols | doc |
|---|---|---|---|
| `monitor_alerts` | one row per alert raised by a monitor (a change in match state over time) | 0 | [doc](raw_complyadvantage/monitor_alerts.md) |
| `monitors` | one row per ongoing monitor registration on a search | 0 | [doc](raw_complyadvantage/monitors.md) |
| `search_hits` | one row per hit (a matched watchlist entity) inside a search | 3 | [doc](raw_complyadvantage/search_hits.md) |
| `searches` | one row per screening search (each search screens one NALA customer) | 2 | [doc](raw_complyadvantage/searches.md) |

### `raw_chainalysis` (3 tables)

| table | grain | PII cols | doc |
|---|---|---|---|
| `address_screenings` | one row per address screening request (one screened wallet address) | 2 | [doc](raw_chainalysis/address_screenings.md) |
| `exposure` | one row per (screening, counterparty-category, direction) exposure breakdown line | 1 | [doc](raw_chainalysis/exposure.md) |
| `screening_alerts` | one row per alert raised off a high-risk screening | 1 | [doc](raw_chainalysis/screening_alerts.md) |

### `raw_compliance` (4 tables)

| table | grain | PII cols | doc |
|---|---|---|---|
| `case_management` | one row per compliance case (an investigation; may or may not become a SAR) | 1 | [doc](raw_compliance/case_management.md) |
| `risk_scores` | one row per customer risk-score snapshot (re-scored periodically and on events) | 0 | [doc](raw_compliance/risk_scores.md) |
| `sanctions_list` | one row per sanctions-list entry (a listed entity) | 3 | [doc](raw_compliance/sanctions_list.md) |
| `sars` | one row per Suspicious Activity Report filed (or drafted) to a regulator/FIU | 4 | [doc](raw_compliance/sars.md) |

## Growth & Product Analytics


### `raw_segment` (5 tables)

| table | grain | PII cols | doc |
|---|---|---|---|
| `groups` | one row per `group` call (associates a user with a merchant/org) | 2 | [doc](raw_segment/groups.md) |
| `identifies` | one row per `identify` call (roughly one per customer, at first sign-in) | 6 | [doc](raw_segment/identifies.md) |
| `pages` | one row per web `page` call (a page view on the marketing site or web app) | 3 | [doc](raw_segment/pages.md) |
| `screens` | one row per mobile `screen` call (an in-app screen view on iOS/Android) | 3 | [doc](raw_segment/screens.md) |
| `tracks` | one row per `track` call (a single user action / product event) | 4 | [doc](raw_segment/tracks.md) |

### `raw_amplitude` (3 tables)

| table | grain | PII cols | doc |
|---|---|---|---|
| `cohorts` | one row per Amplitude cohort definition | 1 | [doc](raw_amplitude/cohorts.md) |
| `events` | one row per Amplitude event | 7 | [doc](raw_amplitude/events.md) |
| `user_properties` | one row per `amplitude_id` (latest known property snapshot per user) | 3 | [doc](raw_amplitude/user_properties.md) |

### `raw_appsflyer` (4 tables)

| table | grain | PII cols | doc |
|---|---|---|---|
| `attributions` | one row per attribution decision record (install / reattribution / reengagement) | 2 | [doc](raw_appsflyer/attributions.md) |
| `in_app_events` | one row per post-install in-app event tracked by AppsFlyer | 3 | [doc](raw_appsflyer/in_app_events.md) |
| `installs` | one row per first-open / install (one per customer) | 6 | [doc](raw_appsflyer/installs.md) |
| `media_sources` | one row per acquisition channel / ad network | 0 | [doc](raw_appsflyer/media_sources.md) |

### `raw_app_store` (4 tables)

| table | grain | PII cols | doc |
|---|---|---|---|
| `apple_downloads` | one row per (report_date, country, app_version, source_type, device) | 0 | [doc](raw_app_store/apple_downloads.md) |
| `apple_reviews` | one row per App Store customer review | 2 | [doc](raw_app_store/apple_reviews.md) |
| `google_play_installs` | one row per (stat_date, country, app_version_code) | 0 | [doc](raw_app_store/google_play_installs.md) |
| `google_play_reviews` | one row per Play Store review | 2 | [doc](raw_app_store/google_play_reviews.md) |

## Marketing, CRM & Support


### `raw_braze` (5 tables)

| table | grain | PII cols | doc |
|---|---|---|---|
| `campaigns` | one row per single-step Braze messaging campaign | 0 | [doc](raw_braze/campaigns.md) |
| `canvases` | one row per multi-step Braze Canvas (orchestration journey) | 0 | [doc](raw_braze/canvases.md) |
| `custom_events` | one row per tracked product/business event forwarded to Braze | 0 | [doc](raw_braze/custom_events.md) |
| `messages_sent` | one row per message send event (Currents-style event stream) | 1 | [doc](raw_braze/messages_sent.md) |
| `segments` | one row per Braze audience segment definition | 0 | [doc](raw_braze/segments.md) |

### `raw_google_ads` (3 tables)

| table | grain | PII cols | doc |
|---|---|---|---|
| `ad_groups` | one row per ad group within a campaign | 0 | [doc](raw_google_ads/ad_groups.md) |
| `ad_performance_daily` | one row per ad group per day (dominant device) | 0 | [doc](raw_google_ads/ad_performance_daily.md) |
| `campaigns` | one row per Google Ads campaign | 0 | [doc](raw_google_ads/campaigns.md) |

### `raw_meta_ads` (3 tables)

| table | grain | PII cols | doc |
|---|---|---|---|
| `ad_insights_daily` | one row per ad set per day (per publisher platform) | 0 | [doc](raw_meta_ads/ad_insights_daily.md) |
| `ad_sets` | one row per ad set within a campaign | 0 | [doc](raw_meta_ads/ad_sets.md) |
| `campaigns` | one row per Meta (Facebook/Instagram) ad campaign | 0 | [doc](raw_meta_ads/campaigns.md) |

### `raw_zendesk` (4 tables)

| table | grain | PII cols | doc |
|---|---|---|---|
| `satisfaction_ratings` | one row per CSAT survey response on a solved ticket | 1 | [doc](raw_zendesk/satisfaction_ratings.md) |
| `ticket_comments` | one row per comment (public reply or private note) on a ticket | 1 | [doc](raw_zendesk/ticket_comments.md) |
| `tickets` | one row per support ticket | 1 | [doc](raw_zendesk/tickets.md) |
| `users` | one row per Zendesk user (end-user, agent, or admin) | 3 | [doc](raw_zendesk/users.md) |

### `raw_intercom` (2 tables)

| table | grain | PII cols | doc |
|---|---|---|---|
| `conversation_parts` | one row per part (message, note, or system action) within a conversation | 1 | [doc](raw_intercom/conversation_parts.md) |
| `conversations` | one row per Intercom conversation (chat thread) | 1 | [doc](raw_intercom/conversations.md) |

## Comms, Finance & HR


### `raw_twilio` (2 tables)

| table | grain | PII cols | doc |
|---|---|---|---|
| `messages` | one row per SMS message (mostly outbound OTP / notification / marketing) | 1 | [doc](raw_twilio/messages.md) |
| `phone_lookups` | one row per phone-number lookup request | 2 | [doc](raw_twilio/phone_lookups.md) |

### `raw_sendgrid` (2 tables)

| table | grain | PII cols | doc |
|---|---|---|---|
| `events` | one row per delivery/engagement event (fanned out from a message) | 2 | [doc](raw_sendgrid/events.md) |
| `messages` | one row per email send | 1 | [doc](raw_sendgrid/messages.md) |

### `raw_netsuite` (6 tables)

| table | grain | PII cols | doc |
|---|---|---|---|
| `departments` | one row per department / cost center | 0 | [doc](raw_netsuite/departments.md) |
| `gl_accounts` | one row per GL account | 0 | [doc](raw_netsuite/gl_accounts.md) |
| `gl_transactions` | one row per GL transaction line | 0 | [doc](raw_netsuite/gl_transactions.md) |
| `subsidiaries` | one row per legal subsidiary / consolidation entity | 0 | [doc](raw_netsuite/subsidiaries.md) |
| `vendor_bills` | one row per vendor bill (AP invoice header) | 0 | [doc](raw_netsuite/vendor_bills.md) |
| `vendors` | one row per vendor | 3 | [doc](raw_netsuite/vendors.md) |

### `raw_workday` (4 tables)

| table | grain | PII cols | doc |
|---|---|---|---|
| `compensation` | one row per employee per compensation change (effective-dated) | 1 | [doc](raw_workday/compensation.md) |
| `departments` | one row per HR department / cost center | 0 | [doc](raw_workday/departments.md) |
| `employees` | one row per employee (worker) | 9 | [doc](raw_workday/employees.md) |
| `time_off` | one row per time-off request | 0 | [doc](raw_workday/time_off.md) |
