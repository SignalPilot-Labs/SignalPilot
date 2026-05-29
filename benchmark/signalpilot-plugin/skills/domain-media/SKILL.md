---
name: domain-media
description: "Media & entertainment domain knowledge: content catalogs, participation tables, ranking determinism."
---

# Media & Entertainment

## WARNING: Use the Broadest Table Available

BEFORE writing any JOIN, check: does the project have BOTH a broad table (all content types) AND narrow tables (one content type only)?

**IF YES** - ALWAYS join to the broad table. Joining to a narrow table silently drops all rows for other content types. A model called `podcast_engagement` does NOT mean you join only to a podcasts table when a broader `all_content` table exists - the model name describes what the output represents, not which source rows to include.

**IF NO** - there is only one content table. Use it.

To verify: run `SELECT COUNT(DISTINCT <key>) FROM <broad_table>` and compare to `SELECT COUNT(DISTINCT <key>) FROM <narrow_table>`. If the broad table has MORE distinct entities, you MUST use it.

## Participation Tables

Tables that record WHO participated in WHAT (credits, casts, rosters, lineups, contributors) contain ALL participant types - actors, directors, producers, writers, coaches, players.

Do NOT filter by participant type based on the model name or task description. The participation table defines the population. Include all rows unless the YML description contains an explicit filter condition.

## Driving Table

When aggregating content metrics, drive FROM the participation/event table (credits, views, ratings, matches), not the content table (movies, players, tournaments). The participation table has one row per event - that is the correct grain.

## Ranking and Scoring

When ranking entities (top-N, best-rated, most-X), use ROW_NUMBER() with a deterministic tiebreaker - the entity's primary key as the final ORDER BY term. Ordering by a non-unique column (rating, count) alone produces different rankings on each run.

NEVER use DENSE_RANK() for top-N selection - DENSE_RANK() can return more than N rows when ties exist at the boundary.
