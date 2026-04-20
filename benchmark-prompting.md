# Benchmark Prompting Guide

Rules for writing agent prompts that don't waste turns, don't contradict themselves, and don't leak evaluation data. Learned from building and debugging Claude Agent SDK benchmark harnesses.

---

## 1. Language Rules

### Be imperative, not suggestive

The agent is not your colleague. It's a function. Tell it what to do.

```
BAD:  "You might want to check the row count"
BAD:  "Consider verifying the schema"
BAD:  "It would be good to run dbt"
GOOD: "Check the row count. If it differs from the reference, your SQL is wrong."
GOOD: "Run dbt run --select <model>. If it fails, load the debugging skill and fix."
```

Use MUST, NEVER, DO NOT, ALWAYS. Reserve "should" and "consider" for genuinely optional actions. If something is required for correctness, don't soften it.

### One instruction per sentence

Compound sentences create ambiguity about which part is the instruction.

```
BAD:  "Read the YML contract and make sure column names match, then write the SQL
       and run dbt to verify it compiles."
GOOD: "Read the YML contract. Column names must match EXACTLY.
       Write the SQL. Run dbt run --select <model> to build it."
```

### Name things exactly

Never say "the tool" or "the file" or "the query." Name it.

```
BAD:  "Use the schema tool to check columns"
GOOD: "Call check_model_schema for each model"

BAD:  "Check the reference file"
GOOD: "Read reference_snapshot.md in the work directory"

BAD:  "Run the build command"
GOOD: "Run dbt run --select <model>"
```

### Explain WHY a rule exists (one line)

Rules without reasons get ignored when they seem inconvenient. A one-line reason makes the agent respect the rule even in edge cases.

```
BAD:  "Do NOT run a bare dbt run."
GOOD: "Do NOT run a bare dbt run — it rebuilds pre-existing models, changing
       surrogate key assignments and breaking FK relationships."

BAD:  "Use LEFT JOIN by default."
GOOD: "Use LEFT JOIN by default — INNER JOIN silently drops rows, and the gold
       standard includes all dimension values even when metrics are NULL."
```

### Kill weasel words

These words add tokens and subtract clarity:

| Kill | Replace with |
|------|-------------|
| "try to" | (delete — just say the action) |
| "make sure" | "verify" or (delete) |
| "be careful to" | (delete) |
| "it's important to" | (delete — if it's important, just state the rule) |
| "you may want to" | (delete or make imperative) |
| "basically" | (delete) |
| "note that" | (delete — just state the fact) |
| "keep in mind" | (delete — just state the fact) |
| "please" | (delete) |

### Aggressive > polite

Politeness is wasted tokens. Agents don't have feelings. Every "please consider" is a turn where the agent might not do the thing.

```
BAD:  "Please remember to check the column types against the reference."
GOOD: "Check column types against reference_snapshot.md. Type mismatches cause
       evaluation failure even when values are identical."
```

---

## 2. Structure Rules

### Number everything sequentially. No gaps, no duplicates, no sub-numbering.

If you have Steps 1-5, there is no Step 0, no Step 3a, no Step 3b. If a step has sub-actions, use a flat numbered list inside it.

When you renumber steps in one place, grep the ENTIRE prompt set (system prompt, user prompt, all skills, all subagent prompts) and update every reference. A step number mismatch between the system prompt and a skill will confuse the agent for the rest of the run.

### Every cross-reference must be verifiable

If you say "see Section 3" — Section 3 must exist. If you say "from Step 2" — Step 2 must produce the thing you're referencing. If you say "read file X" — file X must be created before the agent reaches that instruction.

```
BAD:  "Use the row count from the #1 Rule above"
       (There is no "#1 Rule" — it's called "ROW COUNT VERIFICATION")

BAD:  "Check reference_snapshot.md for the pre-existing row count"
       (Only valid if _snapshot_reference_tables() runs before the agent starts)

GOOD: "Read reference_snapshot.md. It contains row counts and sample data captured
       from pre-existing tables BEFORE dbt run overwrote them."
```

### Skills must not overlap

If two skills cover the same topic, the agent will load both and get confused when they give slightly different advice. Each skill owns a topic exclusively.

```
BAD:  dbt-debugging covers current_date fixes
      dbt-date-spines covers current_date fixes
      (Agent loads one or the other, gets incomplete advice)

GOOD: dbt-debugging says "For current_date issues, load dbt-date-spines skill"
      dbt-date-spines owns the complete fix pattern
```

### Stop conditions must be binary

The agent must know EXACTLY when to stop. "When everything looks good" is not a stop condition. "When dbt run exits 0 AND all CHECK steps pass" is.

```
BAD:  "Stop when you're satisfied with the results"
GOOD: "STOP when: the verifier subagent completes successfully."
GOOD: "STOP when: dbt run exits 0, schema checks pass, row counts match reference."
```

### Front-load the critical information

The agent's attention degrades toward the end of long prompts. Put the most important rules first. Put reference material (source lists, column specs) at the end.

Order:
1. What to do (task + workflow)
2. What NOT to do (rules + constraints)
3. How to do it (tools + skills)
4. Context (schemas, row counts, dependencies)

---

## 3. Contradiction Prevention

### The contradiction checklist

Before shipping any prompt change, run this checklist:

1. **Cross-reference audit**: Every step number, file name, tool name, and skill name mentioned in any prompt — does the target exist?
2. **Inverse scan**: For every "DO X" instruction, search all prompts for "DO NOT X." If found, one of them is wrong or they need a clear condition distinguishing when each applies.
3. **Precondition check**: For every "when X, do Y" — can X actually be true at that point in the workflow? If Step 3 says "use the count from Step 2," does Step 2 actually produce a count?
4. **Scope overlap**: For every topic covered in multiple places (system prompt + skill + subagent), do they say the same thing? If not, one must be authoritative and the others must defer to it.
5. **Default conflict**: If two rules apply to the same situation and give different defaults, the agent will pick one arbitrarily. Merge them or add an explicit priority.

### Common contradiction patterns

**The "no sibling" paradox:**
```
BAD:  "When no sibling exists: use the sibling's pattern"
       (Contradicts its own precondition)
```

**The "trust but don't trust" split:**
```
BAD:  "Trust YML for column names"
      "Do NOT trust YML for grain"
      (Correct, but the boundary is unclear — spell out exactly what to trust)

GOOD: "YML is authoritative for: column names, descriptions, ref dependencies.
       YML is NOT authoritative for: row counts, grain, join types.
       Derive grain from: unique key structure > column list > upstream grain > source cardinality."
```

**The "filter but don't filter" ambiguity:**
```
BAD:  "not_null on key columns implies input filters — exclude those rows"
      "Do NOT use not_null tests to decide join type"
      (Agent reads "exclude rows" as "use INNER JOIN")

GOOD: "not_null on key columns: add WHERE key_col IS NOT NULL to your source CTE.
       This is a WHERE filter, NOT a reason to change JOIN type. Always use LEFT JOIN
       unless a sibling model uses INNER JOIN."
```

### The single-source-of-truth rule

Every fact should live in exactly one place. Other places should point to it, not restate it.

```
BAD:  System prompt says "use LEFT JOIN by default"
      dbt-write skill says "default to LEFT JOIN"
      dbt-debugging skill says "most common cause: INNER JOIN where LEFT JOIN is needed"
      (Three places to update if the rule changes)

GOOD: dbt-write skill OWNS the JOIN default rule.
      System prompt says "see dbt-write skill for JOIN rules"
      dbt-debugging skill says "if zero rows, check JOIN type (see dbt-write skill)"
```

---

## 4. Benchmark Integrity Rules

### Never leak evaluation data into agent prompts

The agent must solve the task using only the information a human would have: the task instruction, the project files, and the database. Anything from the eval config is off-limits.

**Leaked information includes:**
- Which specific tables the evaluator checks (`condition_tabs`)
- Which columns are compared (`condition_cols`)
- Expected row counts from gold
- The gold DB filename or path
- Any prioritization derived from eval config ("priority models")

**How to detect leaks:**
```
grep -r "eval_critical" benchmark/agent/prompts.py
grep -r "condition_tabs" benchmark/runners/
grep -r "gold" benchmark/runners/ | grep -v ".pyc"
```

If any of these appear in prompt text or are used to select/prioritize models for the agent, it's a leak.

**The test:** Could the official evaluation runner produce the same prompt without reading the eval config? If not, you've leaked.

### Never correct the agent's output post-hoc using eval data

These are violations:
- Deduplicating only eval-critical tables
- Adding missing columns only to eval-critical tables
- Dispatching a "name-fix" agent that knows expected table names from eval config
- Running `dbt run --select <eval_critical_models>` (selective build using eval info)

**Allowed post-processing** (uses only project-level information):
- Running `dbt run` or `dbt run --no-fail-fast` (builds everything)
- Flushing DuckDB WAL (infrastructure, not data)
- Deleting MCP connections (cleanup)

### The eval firewall

```
eval_config ──X──> agent prompt       (NEVER)
eval_config ──X──> post-agent fixes   (NEVER)
eval_config ────> evaluation only     (CORRECT)

project files ───> agent prompt       (CORRECT — this is what the agent should read)
project files ───> post-agent fixes   (ACCEPTABLE — e.g. generic dbt run)
```

---

## 5. Token Efficiency

### Don't repeat yourself across prompt layers

The agent sees: system prompt + user prompt + CLAUDE.md + loaded skills. If the same rule appears in three of these, you've spent 3x the tokens for 1x the information — and introduced 3 places where contradictions can creep in.

**Layer responsibilities:**

| Layer | Owns | Does NOT contain |
|-------|------|-----------------|
| System prompt | Workflow steps, tool list, stop condition | Column specs, source lists, row counts |
| User prompt | Task-specific data (models, columns, deps, sources) | Workflow steps, generic rules |
| CLAUDE.md | Connection info, tool catalog, key rules summary | Detailed workflow, task-specific data |
| Skills | Deep domain knowledge per topic | Information from other skills' domains |
| Subagent prompts | Subagent-specific workflow | Main agent workflow |

### Cut ruthlessly

Every sentence in the prompt costs ~1-3 turns of context. A 5000-token system prompt eats into the agent's working memory for the entire run.

Before adding a sentence, ask: "If I remove this, will the agent fail?" If no, remove it.

```
BAD:  "It's very important to remember that in DuckDB, integer division truncates
       the result, so if you're dividing two integers and expect a decimal result,
       you should cast one of the operands to DOUBLE first."

GOOD: "Integer division truncates: 5/2 = 2. Fix: CAST(x AS DOUBLE) / y"
```

---

## 6. Failure Mode Coverage

### Every rule should prevent a specific observed failure

Don't add rules prophylactically. Every rule in the prompt should trace back to a real failure you observed in benchmark results. Document the failure in a comment.

```
GOOD:
  # shopify001: agent left order_adjusted_total as NULL on no-order days,
  # gold expects 0. Calendar-spine models must COALESCE monetary LEFT JOIN columns.
  "When LEFT JOINing metrics onto a calendar spine, COALESCE all monetary and
   count columns to 0. NULL means 'no data' — 0 means 'zero activity on this day.'
   The gold standard uses 0."
```

### Cover the failure, not the symptom

```
BAD:  "Make sure your row count is correct"
       (The agent already "makes sure" — it just makes sure wrong)

GOOD: "dbt_utils.date_spine end_date is EXCLUSIVE. If your data ends on 2024-09-13,
       set end_date to '2024-09-14' — not '2024-09-13'. Off-by-one here silently
       drops the last day."
```

### Name the common failure modes explicitly

Agents learn from examples, not abstractions. List the top failure modes you've actually seen:

```
TOP FAILURE MODES (from benchmark analysis):
1. Value mismatch — NULL where gold expects 0 (COALESCE missing on LEFT JOIN)
2. Row count off-by-one — date spine end_date is exclusive, not inclusive
3. Wrong column order — comparator checks by value vector, not position, but
   extra/missing columns shift indices
4. Type mismatch — VARCHAR vs INTEGER for ID columns
5. Tiebreaker missing — ROW_NUMBER without unique ORDER BY is non-deterministic
```

---

## 7. Subagent Rules

### Subagents must have a single, clear job

```
BAD:  "Verify the models and fix any issues and also check if there are
       missing tables and rename them if needed"
       (Three jobs — verification, fixing, and renaming)

GOOD: "Verify all models that were built or modified. For each model, run CHECK 1
       through CHECK 6. If any check fails, fix the SQL and rebuild that model."
       (One job: verify and fix)
```

### Subagent prompts must be self-contained

The subagent does NOT see the main agent's system prompt, user prompt, or conversation history. Everything it needs must be in its own prompt.

```
BAD:  "Follow the rules from the system prompt"
       (Subagent doesn't have the system prompt)

GOOD: Include all relevant rules directly in the subagent prompt.
```

### Subagents must know what NOT to touch

The most dangerous subagent failure is "fixing" something that was already correct. Every subagent prompt needs an explicit "DO NO HARM" boundary.

```
GOOD: "Do NOT modify models that the main agent did NOT write. Pre-existing
       complete models are correct as-is. Rebuilding them changes surrogate
       key assignments and breaks FK relationships."
```

---

## 8. Testing Your Prompts

### The read-aloud test

Read your prompt aloud as if you're giving instructions to a very literal, very fast intern who will do EXACTLY what you say and NOTHING you don't say. If you hear ambiguity, the agent will find it.

### The adversarial reading

For every instruction, ask: "How could an agent misinterpret this in a way that wastes 20 turns?" Then rewrite to prevent that interpretation.

```
"Check the row count"
→ Agent runs SELECT COUNT(*), sees 100, says "looks right", moves on
→ Never compared against anything — the check was meaningless

"Check the row count against reference_snapshot.md. If it differs, your SQL is wrong.
 Read the snapshot FIRST, record the expected count, THEN query your model."
→ Agent has a concrete comparison target
```

### The deletion test

Remove one sentence at a time. Run the benchmark. If the score doesn't change, that sentence was wasted tokens. If it drops, the sentence is load-bearing — keep it and consider making it more prominent.

### The contradiction grep

After any edit, run:
```bash
# Find all step references across all prompts and skills
grep -rn "Step [0-9]" benchmark/prompts/ benchmark/skills/

# Find all "DO NOT" rules
grep -rn "DO NOT\|NEVER\|do not\|never" benchmark/prompts/ benchmark/skills/

# Find all default behaviors
grep -rn "default\|by default\|always\|ALWAYS" benchmark/prompts/ benchmark/skills/
```

If any step numbers don't match, or any "ALWAYS X" conflicts with a "NEVER X" elsewhere, fix it before running.
