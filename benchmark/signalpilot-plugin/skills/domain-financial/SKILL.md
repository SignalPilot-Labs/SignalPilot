---
name: domain-financial
description: "Financial reporting rules: grain consistency, balance sheets, double-entry ledgers, fiscal year boundaries, period-over-period calculations."
---

# Financial Reporting

## Driving Table

When aggregating transactions or metrics, drive FROM the fact/transaction table (journal_entries, invoices, payments), not the dimension table (accounts, customers). Accounts with zero transactions MUST NOT appear in transaction reports - they have no data to aggregate.

## Grain Consistency

All metrics in a report MUST operate at the same grain - mixing grains produces silently wrong totals.

Use COUNT(*) on a line-item fact table, not COUNT(DISTINCT document_id) - the grain is the line item, not the document, so COUNT(*) is consistent with SUM(amount).

NEVER use COUNT(DISTINCT) just because a key represents a document or entity - a transaction fact table's grain is the transaction row.

Do NOT use a YML column description to choose between COUNT(*) and COUNT(DISTINCT) - descriptions explain semantics, not aggregation method. The source table's grain determines the correct aggregation.

## Balance Sheets

A balance sheet has exactly three components:
1. Regular accounts (ASSET, LIABILITY, EQUITY) - cumulative running balances
2. Retained Earnings - cumulative P&L from ALL prior fiscal years
3. Current Year Earnings - cumulative P&L from the current fiscal year only

Query the project's configuration or organization table for fiscal year end settings - these values vary per tenant and MUST be used to compute the boundary, not hard-coded.

P&L transactions before the fiscal year boundary = Retained Earnings. P&L from the boundary onward = Current Year Earnings.

If the YML description specifies this earnings split, implement it exactly as written.

## Double-Entry Ledgers

Every transaction has offsetting debits and credits - when unioning ledger entries, preserve BOTH sides.

Running balances MUST be computed with a window function ordered by `transaction_date` AND a deterministic tiebreaker (`transaction_id` or a sequence index) - ordering by date alone is non-deterministic when multiple transactions share a timestamp.

## Period-Over-Period

See dbt-workflow "Incremental Models and Period-Over-Period Columns" for the full rule. On first build, period-over-period columns MUST be NULL. Do NOT substitute 0.
