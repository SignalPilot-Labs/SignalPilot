# Post-Grade Review

You just completed a dbt task. The grading is done and the results are in.

## What happened

Your model was compared against the gold solution. The files below show the CORRECT answer:

- `_gold/changes.patch` shows the exact diff the gold solution applies
- `_gold/task.yaml` contains the original task description
- `_gold_applied/models/` contains the CORRECT final SQL files (gold patch applied)
- Your output is in `models/` (what you built)

## How grading works

The eval is an EXCEPT-based row equality test: it compares your model's OUTPUT
rows against the gold's output rows. It never reads your SQL. A difference is a
FAILURE only if it changes the output - the set of rows or any column value.

Structure is NOT graded. Do NOT report as a failure, prompt bug, or wish when the
output matches:
- Model decomposition - building one model vs an intermediate + final split
- CTE vs subquery vs window-function phrasing
- `var('x')` vs `ref('stg_x')` when both resolve to the same table
- Internal formatting, comments, or CTE naming

Trace and report only differences that change which rows or values the model produces.

## Your job now

### 1. Compare your OUTPUT to the gold's OUTPUT

The eval compares output rows, not SQL text (see "How grading works"). Grading already
seeded the gold output and ran the comparison - both are still in your project:
- The gold output rows are in the table `solution__<model>` (one per graded model),
  queryable with `query_database`.
- The exact comparison the eval ran is in `tests/AUTO_<model>_equality.sql`.

For each failed model:
1. Read `tests/AUTO_<model>_equality.sql` to see which columns the eval compares.
2. Run `query_database` both directions:
   `SELECT * FROM <model> EXCEPT SELECT * FROM solution__<model>`
   `SELECT * FROM solution__<model> EXCEPT SELECT * FROM <model>`
   The returned rows are your exact failures. Note which columns hold the differing values.
   A column-count or column-type mismatch error is itself a failure - your model must
   produce the same columns (names, types) as the gold.
3. Read the gold SQL in `_gold_applied/models/<model>.sql` to explain WHY those rows differ.
4. Edit your `models/` and `snapshots/` files to match the gold, then `dbt run` to confirm they build.

Ground every Decision Trace entry in a real output difference from the EXCEPT queries in
step 2. A SQL difference that returns zero EXCEPT rows in both directions is not a failure -
do not report it.

### 2. Write a failure report

Create `failure_report.html` in the project root. This is a self-contained HTML
report (inline CSS, no external deps) with these sections:

#### Executive Summary
- Task description (1 sentence)
- Result: PASS or FAIL with test counts
- Root cause in 1 sentence

#### Decision Trace
A table of every major decision you made during the task:

| # | Decision | What I Did | What Gold Does | Why I Was Wrong |
|---|----------|-----------|---------------|-----------------|

Include decisions about: driving table, column selection, JOINs, filters,
aggregation functions, strategy choices, column aliasing.

#### Tool Output Analysis
For each tool you called (scan_project, map-columns, query_database, verifiers):
- What the tool told you
- How you interpreted it
- Whether the interpretation was correct

#### Discovery Analysis
The eval already revealed the correct output. For each difference between your output and the gold, determine whether the correct choice was DISCOVERABLE during your research phase, or whether no signal for it existed in your inputs.

Your inputs were the task instruction, the project files (models, YML, macros), and the pre-run database. For each wrong decision:
1. Name the exact artifact that would have pointed to the gold's choice: a specific query (`SELECT ...`), a column type or NULL fraction in a source table, a YML column list, a sibling model's SQL, or a scan or map-columns line.
2. Run that query or read that file now. Record what it returns.
3. Classify the miss:
 - DISCOVERABLE: the signal is in your inputs and you did not check it. State the exact research step you skipped.
 - CONTRADICTORY: the signals in your inputs pointed AWAY from the gold (e.g. a sibling model and the YML both include a column the gold omits). Quote each signal and which way it pointed.
 - ABSENT: no artifact in your inputs distinguishes the gold's choice. State what you searched and that nothing separates the gold's choice from the alternative.

For CONTRADICTORY or ABSENT misses, the task may not be solvable from the agent's inputs. Say so plainly. Do NOT invent a signal that is not there.

#### Prompting Report - CRITICAL SECTION

This is the most important section. For EVERY difference between your
output and the gold, answer this question:

**Did the prompts/skills TELL you to do the wrong thing, or did they
fail to tell you the right thing?**

For each wrong decision:
1. **Quote the EXACT rule** you followed (file name, section, the actual text)
2. **Show how the gold contradicts that rule** - if the gold solution does
   the OPPOSITE of what a prompt rule says, that is a PROMPT BUG. Flag it
   clearly: "⚠ PROMPT CONTRADICTS GOLD: rule says X, gold does Y"
3. If no rule existed: say "NO RULE COVERED THIS - I guessed and guessed wrong"
4. If a tool gave you wrong information: say "TOOL GAVE WRONG SIGNAL" and
   name the tool and what it said vs what was correct

Search EVERY layer of your prompt stack, top to bottom:
- **Claude Code system prompt** (the built-in instructions you received at
  the start of this session - your default behaviors, tool usage patterns,
  "be concise" rules, safety rules, etc. If any of these influenced a wrong
  decision, cite them)
- **CLAUDE.md** (the project-level system prompt copied into this workdir)
- **dbt-workflow skill** (the 8-step workflow, skip/don't-skip logic, Step 7
  build rules, Step 8 verification rules)
- **dbt-write skill** (column naming, JOINs, filters, Jinja removal, CTE
  extraction, sibling patterns)
- **Domain skill** (which one did you load? What driving table rule did it
  give you? Did it conflict with other rules?)
- **Verifier agents** (verifier.md, value-verifier.md - what CHECKs ran,
  what they reported, did you follow or override their FAIL?)
- **Other skills** (dbt-snapshots, dbt-debugging, dbt-testing - if loaded)
- **Tool outputs** (scan_project, map-columns, query_database,
  check-driving-table - what they returned and how you used it)

Quote verbatim - do not paraphrase. Include the file name and section for
every rule you cite. If you cannot find the exact text, say "I cannot locate
the exact rule but my behavior was influenced by [description]."

Be EXHAUSTIVE. If your decision was influenced by a combination of rules
from different files, list ALL of them and explain how they interacted.
If two rules contradicted each other, flag it as "⚠ RULE CONFLICT" and
explain which one you followed and why.

#### Prompt Suggestions

For each prompt bug or gap found above, write the EXACT rule text that
would have led to the correct answer. Format as:

**Problem:** `<one sentence describing the wrong decision>`
**Current rule:** `<quote the rule that was wrong or "NONE">`
**File:** `<skill file path>`
**Proposed fix:** `<the exact text to add, change, or remove>`
**Why it helps:** `<one sentence>`

Rules for suggestions:
- Must be general-purpose (not task-specific)
- Must not contradict existing rules in other files
- Prefer narrowing existing rules over adding new ones
- Prefer tool-level fixes over prompt rules
- If a rule is CORRECT but the gold contradicts it, say so - the rule
  may be right and the gold may be an edge case

#### Wishes
What you WISH you had in your context, tooling, or discovery to get the
correct answer. Be specific and actionable. Examples:
- "I wish map-columns had told me a column is VARCHAR not BLOB"
- "I wish the scan had flagged the parent table as the driving table"
- "I wish the verifier had caught my COALESCE placement"

Rules for wishes:
- Do NOT wish for more information in the task description
- Do NOT wish the user had told you something
- ONLY wish for improvements to: MCP tools, skills, verifier agents, scan output
- Each wish must be specific enough to implement as a code change

#### Diff Summary
For each model file, show what changed between your version and the gold:
- Lines added
- Lines removed
- The semantic meaning of each change

### 3. Format

Use clean HTML with inline CSS. Same style rules as the write-report skill:
- Sans-serif font, max-width 900px, centered
- Color: #22c55e PASS, #ef4444 FAIL, #f59e0b WARN
- Collapsible `<details>` for long sections
- Tables with alternating row colors
