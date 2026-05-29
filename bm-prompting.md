# Benchmark Prompting Guide

Rules for agent prompts. Short prompts > long prompts. Every word earns its place.

---

## 1. Language

**Imperative, not suggestive.** The agent is a function. Tell it what to do.

- BAD: "You might want to check the row count"
- GOOD: "Check the row count against reference_snapshot.md."

**One instruction per sentence.** Compound sentences create ambiguity.

**Name things exactly.** Never "the tool" or "the file." Say `check_model_schema`, `reference_snapshot.md`, `dbt run --select <model>`.

**One-line reason per rule.** Rules without reasons get ignored.

- BAD: "Do NOT run a bare dbt run."
- GOOD: "Do NOT run a bare dbt run — it rebuilds pre-existing models, breaking FK relationships."

**Kill filler.** Delete: "try to", "make sure", "be careful to", "it's important to", "note that", "please", "basically", "keep in mind", "you may want to", "consider".

**Short > long.** If you can say it in 10 words, don't use 30.

- BAD: "It's very important to remember that in DuckDB, integer division truncates the result, so if you're dividing two integers and expect a decimal result, you should cast one of the operands to DOUBLE first."
- GOOD: "Integer division truncates: 5/2 = 2. Fix: CAST(x AS DOUBLE) / y"

---

## 2. Structure

**Sequential numbering.** Steps 1-8, no gaps, no sub-numbering (no 3a, 3b). When you renumber, grep ALL prompts and skills for stale references.

**Within a file, references must resolve.** "See Section 3" — Section 3 must exist. "Use the count from Step 2" — Step 2 must produce a count. These are intra-document references inside one prompt's sequential flow — they are fine.

**No cross-skill references.** One skill owns one topic. Other skills do NOT mention it — not by restating it, not by pointing to it ("see dbt-write", "per the duckdb-sql skill"). Skills load into one shared context in load order. If the owning skill loaded earlier, its rule is already in the prompt — a pointer adds a second voice on a topic already covered. If it loaded later or not at all, the pointer dangles. Either way the reference is noise. A skill that does not own a topic stays silent on it, or scopes its own rule with a self-contained boundary ("in standalone queries") that names no other skill.

**Binary stop conditions.** "STOP when both verifier reports show all checks PASS." Not "when it looks good."

**Front-load critical info.** Agent attention degrades at end of prompt. Order: what to do → what NOT to do → how → context.

**Layer responsibilities (don't repeat across layers):**

| Layer | Owns |
|-------|------|
| System prompt | Workflow steps, stop condition |
| User prompt | Task-specific data (models, columns, deps) |
| CLAUDE.md | Connection info, tool catalog |
| Skills | Domain knowledge per topic |
| Subagent prompts | Subagent-specific workflow |

---

## 3. Contradictions

Before shipping any change, check:

1. **Reference audit** — every intra-file step/section/tool name referenced must exist; no skill names or points to another skill (§2)
2. **Inverse scan** — for every "DO X", search for "DO NOT X" elsewhere. If found, one is wrong or they need a distinguishing condition
3. **Precondition check** — "use the count from Step 2" only works if Step 2 produces a count
4. **Scope overlap** — a topic must live in exactly ONE skill. If it appears in two, delete the non-owner's copy and let the owner stand alone
5. **Default conflict** — two rules giving different defaults for the same situation → merge or prioritize

**Single source of truth.** Every fact lives in one place. Other skills neither restate it nor point to it — the owning skill is already in context when they load (see §2 No cross-skill references).

---

## 4. Benchmark Integrity

**Never leak evaluation data into prompts.** The agent gets only what a human would have: task instruction, project files, database.

Leaked = off-limits:
- Which tables the evaluator checks
- Which columns are compared
- Expected row counts from gold
- Gold DB path
- Any prioritization from eval config

**Never correct output post-hoc using eval data.** No selective builds, no name-fix agents, no dedup of only eval-critical tables.

**The eval firewall:**
- eval_config → agent prompt: NEVER
- eval_config → post-agent fixes: NEVER
- eval_config → evaluation only: CORRECT
- project files → agent prompt: CORRECT

---

## 5. Prompt Changes

**Prefer minimal changes.** One new sentence > one new paragraph. One new rule > one new section. If a fix can be 10 words appended to an existing rule, don't write a new rule.

**Every rule must trace to a real failure.** Don't add rules prophylactically. If you can't name the task that failed without this rule, delete it. But the trace stays in YOUR notes — it never appears in the skill text itself.

**Skills and prompts are production artifacts, not debug logs.** Never include benchmark task names, failure references, trace annotations, or phrases like "Traced to airbnb012" in skill text. The agent reading the skill doesn't know what airbnb012 is — it just sees noise. Write rules as if no benchmark exists. The reason for a rule should be self-evident from the rule itself ("Read the SQL first — column names must be exact") not from a parenthetical citing a test failure.

**Cover the cause, not the symptom.**

- BAD: "Make sure your row count is correct"
- GOOD: "dbt_utils.date_spine end_date is EXCLUSIVE. Data ending 2024-09-13 needs end_date '2024-09-14'."

**Use examples — but never from the benchmark.** Illustrate rules with generic dbt/SQL patterns, not specific benchmark task data. Good examples use invented table names (my_orders, dim_products). Bad examples reference actual benchmark schemas (shopify__daily_shop, tpch_lineitem).

**Test by deletion.** Remove one sentence. Run the benchmark. If the score doesn't change, that sentence was wasted tokens.

---

## 6. Subagents

**Single job.** Each subagent does one thing. "Verify and fix" is one job. "Verify, fix, rename, and also check for missing tables" is four jobs.

**Self-contained.** The subagent doesn't see the main agent's prompt. Everything it needs goes in its own prompt.

**DO NO HARM boundary.** Every subagent prompt must say what NOT to touch. Pre-existing models are correct — don't "fix" them.

---

## Summary

Good prompts are short, imperative, non-contradictory, and traceable to real failures. They use examples (never from the benchmark itself). They prefer appending 10 words to an existing rule over writing a new section. They never leak eval data. They name things exactly and stop on binary conditions.
