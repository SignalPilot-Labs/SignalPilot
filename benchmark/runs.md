# Spider2-DBT Benchmark Runs

## Score: 25/63 evaluable = 39.7%

## Passing Tasks (25)

| Task | Tables Checked | Notes |
|------|---------------|-------|
| activity001 | dataset__* (19 tables) | Flipped by "model discovery beyond YAML" skill |
| airport001 | airport models | Clean pass |
| app_reporting001 | reporting models | Clean pass |
| app_reporting002 | reporting models | Clean pass |
| asana001 | asana__* models | Clean pass |
| google_play001 | play store models | Clean pass |
| google_play002 | play store models | Recovered after retry |
| greenhouse001 | application_enhanced, job_enhanced | **NEW FLIP** — MCP tools helped with schema discovery |
| hubspot001 | hubspot__* models | Recovered after retry |
| lever001 | lever__* models | Clean pass |
| marketo001 | marketo__* models | Clean pass |
| maturity001 | maturity models | Clean pass |
| mrr001 | mrr__* models | Flipped by MRR change_category skill fix |
| mrr002 | mrr__* models | Flipped by MRR change_category skill fix; recovered after retry |
| playbook001 | attribution_touches | Clean pass |
| qualtrics001 | qualtrics__* models | Clean pass |
| quickbooks002 | quickbooks__* models | Clean pass |
| retail001 | retail models | Clean pass |
| salesforce001 | salesforce__* models | **NEW FLIP** — Date spine fix flipped this task |
| shopify002 | shopify__* models | Recovered after retry |
| shopify_holistic_reporting001 | reporting models | Flipped by MCP tools; recovered after retry |
| tickit001 | tickit models | Clean pass |
| tickit002 | tickit models | Flipped by MCP tools |
| workday001 | workday__* models | Clean pass |
| workday002 | workday__* models | Clean pass |

## Failing Tasks (38 evaluable failures)

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
| f1002 | Tables built but values wrong (finishes_by_constructor, driver_championships) | D - Logic | Values consistently wrong across runs | Requires deeper investigation into F1 logic for these tables |
| f1003 | stg_f1_dataset__drivers driver_current_age values wrong | D - Logic | Uses current_date for age calculation instead of a fixed reference date | Replace current_date with a fixed reference date matching gold |
| flicks001 | Both FAIL (56754→44729, 60983→57546) | B - JOIN | INNER JOIN between credits and movies drops actors not in movies | Include shows or use LEFT JOIN; check if credits span movies+shows |
| hive001 | covid_cases 510 vs 558 rows consistently | C - Row count | Row count consistently short by 48 rows | Investigate filtering logic that drops rows from covid_cases |
| intercom001 | company PASS, admin FAIL (4 vs 1) | C - Grain | Agent groups by closed conversations → only 1 admin. Gold expects all 4 admins (including those with 0 conversations) | Start from admin table, LEFT JOIN to conversations |
| inzight001 | FAIL - column value mismatch | D - Logic | Peak value tie-breaking is non-deterministic when multiple records share monthly peak | Add deterministic tie-breaking for peak records |
| jira001 | jira__project_enhanced MISSING | E - Build | DuckDB type conflict (VARCHAR vs DATE) in pivot operation | Cast field_id consistently as VARCHAR before pivot |
| netflix001 | FAIL (99 vs 109) | C - Dedup | UNION ALL includes duplicates; gold uses UNION or filters some rows | Switch UNION ALL to UNION, or add dedup/filter logic |
| pendo001 | page_daily_metrics PASS, guide_daily_metrics FAIL (4686 vs 1311) | A - Date spine | Calendar spine uses `current_date + 1 week` as end; page now fixed, guide still wrong | Cap guide spine end at max source event date |
| playbook002 | attribution PASS, cpa FAIL (5 vs 2) | B - JOIN | INNER JOIN between attribution and spend drops sources with no spend | Change to LEFT JOIN or FULL OUTER JOIN |
| provider001 | provider PASS, specialty FAIL (874 vs 460) | B - JOIN | Agent joins only codes WITH Medicare crosswalk entries | LEFT JOIN from nucc_taxonomy to crosswalk, keeping all 874 codes |
| quickbooks001 | FAIL - unique_id values wrong | D - Logic | Surrogate key uses different field list than gold's canonical definition | Match exact surrogate_key field list from reference implementation |
| quickbooks003 | Both FAIL (276→352, 759→968) | A - Date spine | General ledger date spine uses current_date, extending beyond source data | Cap spine end at max(transaction_date) |
| recharge001 | FAIL - amount values wrong | D - Logic | Decimal precision or sort order for charge_row_num differs from gold | Align amount precision and row numbering sort order |
| recharge002 | customer_daily_rollup 124-134 vs 122 rows consistently | C - Row count | Row count consistently high by 2-12 rows across runs | Investigate date spine or join logic adding extra rows |
| reddit001 | posts FAIL (30970 vs 30971), comments FAIL (column missing) | F+C | Off by 1 row + missing hour_comment_created_at column | Add missing column; investigate 1-row discrepancy |
| sap001 | Both FAIL (0 rows) | E+G | UNPIVOT produces empty results — likely source data issue or DuckDB UNPIVOT compatibility | Verify source data loaded; check DuckDB UNPIVOT syntax |
| scd001 | fct PASS, rpt FAIL (values wrong) | D - Logic | arg_min/arg_max tiebreakers for first_user_id differ from gold | Reverse-engineer gold's tiebreaker logic |
| shopify001 | products PASS, daily_shop FAIL (2082 vs 2077, only 5 off) | A - Date spine | Calendar uses current_date; improved from 2654→2082 rows (gold=2077) | Cap spine at max(order_date) from source |
| social_media001 | twitter PASS, instagram FAIL, rollup FAIL | F - Schema | Instagram impressions formula differs; column names mismatch | Align impressions formula and column names with gold |
| superstore001 | Both FAIL (id values wrong) | G - Non-deterministic | ROW_NUMBER() OVER (ORDER BY NULL) produces non-deterministic IDs | Add deterministic ORDER BY to ROW_NUMBER in dimension tables |
| synthea001 | FAIL (808 vs 809, 1 off) | C - Off by 1 | 1 row missing; improved from 807→808 vs gold 809 | Identify which cost source drops the final row |
| tpch001 | client_purchase_status fan-out (76777-150000 vs 75007) | C - Row count | Fan-out in join produces consistently wrong row counts | Investigate join keys causing fan-out in client_purchase_status |
| tpch002 | Both tables MISSING | E - Build | Agent left placeholder stubs, never wrote actual SQL | Implement TPC-H Query 2 variants for EUR and UK suppliers |
| twilio001 | number PASS, account FAIL | D - Logic | total_messages_spend sums all messages; gold may only count outbound | Verify which message types contribute to spend total |
| xero001 | FAIL (1194 vs 1170, 24 off) | A - Date spine | Calendar spine uses current_date + 1 month; improved from 1574→1194 rows (gold=1170) | Cap at max(journal_date) |
| xero_new001 | FAIL (column + row mismatch) | A+F | Same CURRENT_DATE spine + column schema differences | Fix spine + align column list |
| xero_new002 | FAIL (1194 vs 1170, 24 off) | A - Date spine | Same as xero001; improved from 1574→1194 rows (gold=1170) | Cap at max(journal_date) |
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
| A - Date spine/CURRENT_DATE | 7 | **Highest ROI fix** — single improvement could flip remaining tasks |
| B - Wrong JOIN type | 4 | Medium — skill exists but agent doesn't consistently apply |
| C - Row count/aggregation | 7 | Mixed — some are agent reasoning failures, some are consistent regressions |
| D - Value/computation error | 9 | Hard — task-specific logic errors |
| E - Missing/broken build | 3 | Medium — some are DuckDB compatibility issues |
| F - Schema/column mismatch | 3 | Fixable — column list alignment |
| G - Unfixable/non-deterministic | 2 | Can't fix without fundamental changes |

## Consistent Regressions (tasks that were passing but now consistently fail)

| Task | Symptom | Likely Cause |
|------|---------|--------------|
| f1002 | finishes_by_constructor, driver_championships values wrong | F1 domain logic error introduced or exposed |
| f1003 | driver_current_age values wrong | Uses current_date for age calc instead of fixed reference date |
| hive001 | covid_cases 510 vs 558 rows consistently | Filtering change drops 48 rows |
| recharge002 | customer_daily_rollup 124-134 vs 122 rows consistently | Date spine or join producing extra rows |
| tpch001 | client_purchase_status fan-out (76777-150000 vs 75007) | Join fan-out on client_purchase_status |
