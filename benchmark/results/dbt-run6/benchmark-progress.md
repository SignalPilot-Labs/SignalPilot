# Run6 Full Benchmark Results

## Score: 38/64 (59.4%)

- **Run4 baseline**: 33/64 (51.6%)
- **Run6 result**: 38/64 (59.4%)
- **Net change**: +5
- **Flips**: 7 new passes
- **Regressions**: 2 tasks that passed in run4 now fail

## Results

| # | Task | Run4 | Run6 | Remark |
|---|------|------|------|--------|
| 1 | activity001 | PASS | PASS |  |
| 2 | airbnb001 | PASS | PASS |  |
| 3 | airport001 | PASS | PASS |  |
| 4 | analytics_engineering001 | FAIL | FAIL |  |
| 5 | app_reporting001 | PASS | PASS |  |
| 6 | app_reporting002 | PASS | PASS |  |
| 7 | apple_store001 | PASS | PASS |  |
| 8 | asana001 | PASS | PASS |  |
| 9 | asset001 | FAIL | PASS | NEW FLIP |
| 10 | atp_tour001 | FAIL | FAIL |  |
| 11 | chinook001 | PASS | PASS |  |
| 12 | divvy001 | PASS | PASS |  |
| 13 | f1001 | FAIL | FAIL |  |
| 14 | f1002 | PASS | PASS |  |
| 15 | f1003 | PASS | PASS |  |
| 16 | flicks001 | FAIL | FAIL |  |
| 17 | google_play001 | FAIL | PASS | NEW FLIP |
| 18 | google_play002 | PASS | PASS |  |
| 19 | greenhouse001 | PASS | PASS |  |
| 20 | hive001 | FAIL | FAIL |  |
| 21 | hubspot001 | PASS | PASS |  |
| 22 | intercom001 | PASS | PASS |  |
| 23 | inzight001 | FAIL | FAIL |  |
| 24 | jira001 | FAIL | FAIL |  |
| 25 | lever001 | PASS | PASS |  |
| 26 | marketo001 | PASS | PASS |  |
| 27 | maturity001 | PASS | PASS |  |
| 28 | movie_recomm001 | FAIL | FAIL |  |
| 29 | mrr001 | PASS | PASS |  |
| 30 | mrr002 | PASS | PASS |  |
| 31 | nba001 | FAIL | FAIL |  |
| 32 | netflix001 | FAIL | FAIL |  |
| 33 | pendo001 | FAIL | PASS | NEW FLIP |
| 34 | playbook001 | PASS | PASS |  |
| 35 | playbook002 | FAIL | FAIL |  |
| 36 | provider001 | FAIL | FAIL |  |
| 37 | qualtrics001 | PASS | PASS |  |
| 38 | quickbooks001 | FAIL | FAIL |  |
| 39 | quickbooks002 | PASS | PASS |  |
| 40 | quickbooks003 | PASS | PASS |  |
| 41 | recharge001 | FAIL | FAIL |  |
| 42 | recharge002 | PASS | PASS |  |
| 43 | reddit001 | FAIL | PASS | NEW FLIP |
| 44 | retail001 | PASS | PASS |  |
| 45 | salesforce001 | PASS | FAIL | REGRESSION |
| 46 | sap001 | FAIL | FAIL |  |
| 47 | scd001 | FAIL | FAIL |  |
| 48 | shopify001 | PASS | PASS |  |
| 49 | shopify002 | PASS | PASS |  |
| 50 | shopify_holistic_reporting001 | FAIL | PASS | NEW FLIP |
| 51 | social_media001 | FAIL | FAIL |  |
| 52 | superstore001 | PASS | FAIL | REGRESSION |
| 53 | synthea001 | FAIL | FAIL |  |
| 54 | tickit001 | PASS | PASS |  |
| 55 | tickit002 | FAIL | FAIL |  |
| 56 | tpch001 | FAIL | PASS | NEW FLIP |
| 57 | tpch002 | FAIL | FAIL |  |
| 58 | twilio001 | FAIL | FAIL |  |
| 59 | workday001 | PASS | PASS |  |
| 60 | workday002 | PASS | PASS |  |
| 61 | xero001 | FAIL | FAIL |  |
| 62 | xero_new001 | FAIL | FAIL |  |
| 63 | xero_new002 | FAIL | FAIL |  |
| 64 | zuora001 | FAIL | PASS | NEW FLIP |

## Flips (7)

- **asset001**: NEW PASS
- **google_play001**: NEW PASS
- **pendo001**: NEW PASS
- **reddit001**: NEW PASS
- **shopify_holistic_reporting001**: NEW PASS
- **tpch001**: NEW PASS
- **zuora001**: NEW PASS

## Regressions (2)

- **salesforce001**: was PASS in run4, now FAIL
- **superstore001**: was PASS in run4, now FAIL
