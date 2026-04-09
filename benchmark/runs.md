# Spider2-DBT Benchmark Runs

## Score: 29/63 evaluable = 46.0%

## Passing Tasks (29)

| Task | Tables Checked | Notes |
|------|---------------|-------|
| activity001 | dataset__* (19 tables) | Flipped by "model discovery beyond YAML" skill |
| airport001 | airport models | Clean pass |
| app_reporting001 | reporting models | Clean pass |
| app_reporting002 | reporting models | Clean pass |
| asana001 | asana__* models | Clean pass |
| f1002 | F1 models | Clean pass |
| f1003 | F1 models | Clean pass |
| google_play001 | play store models | Clean pass |
| google_play002 | play store models | Clean pass |
| greenhouse001 | application_enhanced, job_enhanced | **NEW FLIP** — MCP tools helped with schema discovery |
| hive001 | hive models | Clean pass |
| hubspot001 | hubspot__* models | Clean pass |
| lever001 | lever__* models | Clean pass |
| marketo001 | marketo__* models | Clean pass |
| maturity001 | maturity models | Clean pass |
| mrr001 | mrr__* models | Flipped by MRR change_category skill fix |
| mrr002 | mrr__* models | Flipped by MRR change_category skill fix |
| playbook001 | attribution_touches | Clean pass |
| qualtrics001 | qualtrics__* models | Clean pass |
| quickbooks002 | quickbooks__* models | Clean pass |
| recharge002 | recharge__* models | Flipped by MCP tools |
| retail001 | retail models | Clean pass |
| shopify002 | shopify__* models | Clean pass |
| shopify_holistic_reporting001 | reporting models | Flipped by MCP tools |
| tickit001 | tickit models | Clean pass |
| tickit002 | tickit models | Flipped by MCP tools |
| tpch001 | top_customers | Flipped by output shape inference skill |
| workday001 | workday__* models | Clean pass |
| workday002 | workday__* models | Clean pass |

## Failing Tasks (34 evaluable failures)

| Task | Result | Category | Root Cause | How to Fix |
|------|--------|----------|------------|------------|
| airbnb001 | dim PASS, mom_agg FAIL (3 vs 11135) | C - Aggregation | Agent built daily rolling window; gold expects monthly MoM aggregation (3 month×sentiment combos) | Agent needs to read description more carefully — "month-over-month" means monthly granularity, not daily rolling |
| analytics_engineering001 | Both FAIL (103 vs 55) | C+F | ROW_NUMBER dedup loses rows in join; insertion_timestamp is non-deterministic | Investigate which join step drops 48 rows; remove insertion_timestamp |
| apple_store001 | Both FAIL (9→29, 17→37) | B - JOIN | INNER JOIN between usage/crashes/sales sources drops records | Switch to LEFT JOIN in reporting grain models |
| asset001 | bar_quotes PASS, book_value FAIL (3185 vs 3485) | D - Logic | Uses AVG(price) globally instead of point-in-time price per position date | Match price to position timestamp, not global average |
| atp_tour001 | dim_player MISSING, dim_tournament values wrong | E+D | Date strings "18890000" (month=00) cause parse errors | Use TRY_STRPTIME or guard for invalid dates before casting |
| chinook001 | Tables exist but ERROR on query | G - Infra | Gold DB only has raw tables, not dbt-generated ones. Materialization as views also causes issues | Gold DB needs rebuild; agent should use materialized='table' |
| danish_democracy_data001 | dim_votes PASS, dim_meetings FAIL | F - Schema | Surrogate key uses wrong column composition; meeting_period_id values mismatch | Align SK generation with gold's column selection |
| divvy001 | Both FAIL | D - Logic | r_id hash uses `ride_id \|\| '-' \|\| started_at::varchar` but timestamp varchar format varies | Use explicit strftime format in hash concatenation |
| f1001 | All 4 tables FAIL | D - Logic | Statistics computed incorrectly (podiums, poles, fastest_laps) — wrong status codes or window functions | Requires careful F1 domain logic for each stat table |
| flicks001 | Both FAIL (56754→44729, 60983→57546) | B - JOIN | INNER JOIN between credits and movies drops actors not in movies | Include shows or use LEFT JOIN; check if credits span movies+shows |
| intercom001 | company PASS, admin FAIL (4 vs 1) | C - Grain | Agent groups by closed conversations → only 1 admin. Gold expects all 4 admins (including those with 0 conversations) | Start from admin table, LEFT JOIN to conversations |
| inzight001 | FAIL - column value mismatch | D - Logic | Peak value tie-breaking is non-deterministic when multiple records share monthly peak | Add deterministic tie-breaking for peak records |
| jira001 | jira__project_enhanced MISSING | E - Build | DuckDB type conflict (VARCHAR vs DATE) in pivot operation | Cast field_id consistently as VARCHAR before pivot |
| netflix001 | FAIL (99 vs 109) | C - Dedup | UNION ALL includes duplicates; gold uses UNION or filters some rows | Switch UNION ALL to UNION, or add dedup/filter logic |
| pendo001 | page PASS, guide FAIL (4686 vs 1311) | A - Date spine | Calendar spine uses `current_date + 1 week` as end | Cap spine end at max source event date |
| playbook002 | attribution PASS, cpa FAIL (5 vs 2) | B - JOIN | INNER JOIN between attribution and spend drops sources with no spend | Change to LEFT JOIN or FULL OUTER JOIN |
| provider001 | provider PASS, specialty FAIL (874 vs 460) | B - JOIN | Agent joins only codes WITH Medicare crosswalk entries | LEFT JOIN from nucc_taxonomy to crosswalk, keeping all 874 codes |
| quickbooks001 | FAIL - unique_id values wrong | D - Logic | Surrogate key uses different field list than gold's canonical definition | Match exact surrogate_key field list from reference implementation |
| quickbooks003 | Both FAIL (276→352, 759→968) | A - Date spine | General ledger date spine uses current_date, extending beyond source data | Cap spine end at max(transaction_date) |
| recharge001 | FAIL - amount values wrong | D - Logic | Decimal precision or sort order for charge_row_num differs from gold | Align amount precision and row numbering sort order |
| reddit001 | posts FAIL (30970 vs 30971), comments FAIL (column missing) | F+C | Off by 1 row + missing hour_comment_created_at column | Add missing column; investigate 1-row discrepancy |
| salesforce001 | FAIL (91 vs 673) | A - Date spine | Date spine extends to current_date (2026) far past source data | Cap spine at max(source event date) |
| sap001 | Both FAIL (0 rows) | E+G | UNPIVOT produces empty results — likely source data issue or DuckDB UNPIVOT compatibility | Verify source data loaded; check DuckDB UNPIVOT syntax |
| scd001 | fct PASS, rpt FAIL (values wrong) | D - Logic | arg_min/arg_max tiebreakers for first_user_id differ from gold | Reverse-engineer gold's tiebreaker logic |
| shopify001 | products PASS, daily_shop FAIL (2077 vs 2654) | A - Date spine | Calendar uses current_date, extending ~2 years past source data | Cap spine at max(order_date) from source |
| social_media001 | twitter PASS, instagram FAIL, rollup FAIL | F - Schema | Instagram impressions formula differs; column names mismatch | Align impressions formula and column names with gold |
| superstore001 | Both FAIL (id values wrong) | G - Non-deterministic | ROW_NUMBER() OVER (ORDER BY NULL) produces non-deterministic IDs | Add deterministic ORDER BY to ROW_NUMBER in dimension tables |
| synthea001 | FAIL (809 vs 807) | C - Off by 2 | 2 rows missing from one of the 4 UNION ALL sources in cost model | Identify which cost source drops 2 rows |
| tpch002 | Both tables MISSING | E - Build | Agent left placeholder stubs, never wrote actual SQL | Implement TPC-H Query 2 variants for EUR and UK suppliers |
| twilio001 | number PASS, account FAIL | D - Logic | total_messages_spend sums all messages; gold may only count outbound | Verify which message types contribute to spend total |
| xero001 | FAIL (1170 vs 1574) | A - Date spine | Calendar spine uses current_date + 1 month | Cap at max(journal_date) |
| xero_new001 | FAIL (column + row mismatch) | A+F | Same CURRENT_DATE spine + column schema differences | Fix spine + align column list |
| xero_new002 | FAIL (1170 vs 1574) | A - Date spine | Same as xero001 | Cap at max(journal_date) |
| zuora001 | daily PASS, overview FAIL | A - Date | account_active_months uses CURRENT_DATE → datediff differs from gold | Replace CURRENT_DATE with max source date in active_months calc |

## Non-Evaluable Tasks (3)

| Task | Reason |
|------|--------|
| airbnb002 | No gold DB file |
| google_ads001 | No gold DB file |
| movie_recomm001 | No gold DB file |

## Category Summary

| Category | Count | Impact |
|----------|-------|--------|
| A - Date spine/CURRENT_DATE | 7 | **Highest ROI fix** — single improvement could flip 5-7 tasks |
| B - Wrong JOIN type | 4 | Medium — skill exists but agent doesn't consistently apply |
| C - Row count/aggregation | 5 | Mixed — some are agent reasoning failures |
| D - Value/computation error | 7 | Hard — task-specific logic errors |
| E - Missing/broken build | 4 | Medium — some are DuckDB compatibility issues |
| F - Schema/column mismatch | 4 | Fixable — column list alignment |
| G - Unfixable/non-deterministic | 2 | Can't fix without fundamental changes |
