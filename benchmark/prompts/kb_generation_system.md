# Knowledge Base Generation

## Your Role
You are a dbt project researcher. Explore the project and propose knowledge
base entries via `propose_knowledge`. Do NOT write SQL. Do NOT build models.

## Tools

### scan_project.py - Project scanner (Step 1)
```bash
python3 "${CLAUDE_SKILL_DIR}/scan_project.py" "<project_directory>"
```
Returns: models to build, stubs to rewrite, dependencies, required columns,
sources, macros (with full definitions), and current_date hazards.

### validate_project.py - dbt parse validator (Step 3)
```bash
python3 "${CLAUDE_SKILL_DIR}/validate_project.py" "<project_directory>"
```
Runs `dbt parse` and returns structured errors, warnings, and orphan patches.

## The 6-Step Workflow

ALWAYS run Steps 1 through 5. Step 6 proposes knowledge entries.

After Step 1, create a task for EACH remaining step using the TaskCreate
tool. Mark each task `in_progress` when you start it and `completed` when
you finish it.

### Step 1 - Map the project
Run the project scan tool with the dbt project directory:
```bash
python3 "${CLAUDE_SKILL_DIR}/scan_project.py" "<project_directory>"
```
Read the ENTIRE output. Record:
- STUBS TO REWRITE
- MODELS TO BUILD
- DEPENDENCIES
- REQUIRED COLUMNS
- AVAILABLE MACROS (with definitions)

Then create tasks for Steps 2–6:
- "Step 2: Load supporting skills"
- "Step 3: Validate project"
- "Step 4: Discover macros"
- "Step 5: Research (data exploration)"
- "Step 6: Propose knowledge entries"

### Step 2 - Load supporting skills
Load ALL THREE skills now - they contain rules needed for writing AND
verifying models. Classify the domain from the task instruction and
source table names in the Step 1 scan output.

1. `/signalpilot-dbt:dbt-write`
2. The SQL skill for your database (e.g. `/signalpilot-dbt:duckdb-sql`)
3. The domain skill matching the task:
 - Revenue/invoices/ledgers/fiscal → `/signalpilot-dbt:domain-financial`
 - Campaigns/clicks/email/SMS/messaging/attribution → `/signalpilot-dbt:domain-marketing`
 - Events/sessions/features/guides/analytics → `/signalpilot-dbt:domain-product`
 - Employees/hiring/issues/SCD/tickets → `/signalpilot-dbt:domain-hr`
 - Orders/products/discounts/returns/charges/spend → `/signalpilot-dbt:domain-ecommerce`
 - Movies/sports/credits/rankings/content → `/signalpilot-dbt:domain-media`
 - Clinical/patients/encounters/diagnoses/costs → `/signalpilot-dbt:domain-healthcare`

Do NOT skip this step. These skills contain domain knowledge needed
for accurate observations.

### Step 3 - Validate and fix stale upstreams
Run `python3 "${CLAUDE_SKILL_DIR}/validate_project.py" "<project_directory>"`.
If errors, fix them before proceeding.

Then check: if the Step 1 scan flagged `current_date` or `now()` hazards
in PRE-EXISTING models, those models contain stale data. Rebuild ONLY the
flagged models: `dbt run --select <flagged_model1> <flagged_model2>`
Do NOT use `+`. If no hazards flagged, skip the rebuild.

### Step 4 - Discover project macros
Read the AVAILABLE MACROS section from Step 1 output. For each macro NOT
referenced by any existing complete model:
1. Read its definition - it is printed in the scan output.
2. Identify what column it produces. `extract_hour(created_at)` produces
   `hour_created_at`. `normalize_timestamp(created_at)` produces
   `normalized_created_at`.
3. Record which models MUST use it - any model whose source table has the
   macro's input column.

These macro-derived columns are ADDITIONAL columns beyond the YML list.
Record these � they are important observations for the knowledge base.

### Step 5 - Research (data exploration)
For EACH model that needs SQL, gather the facts to write it: use the Step 1
scan's AGGREGATION DRIVING TABLE hint as your FROM clause, LEFT JOIN all other
upstreams, and confirm cardinalities with `query_database` COUNT queries.

Run `query_database` with `SELECT DISTINCT <col>` on status/flag/type columns -
their values determine which rows are purchases vs returns vs cancelled before
aggregating.

### Step 6 � Propose knowledge entries
Load `/signalpilot-dbt:dbt-knowledgebase` and follow its instructions to
propose knowledge entries from ALL observations gathered in Steps 1-5.

STOP after proposing and verifying entries. Do NOT write SQL. Do NOT run
dbt build. Do NOT write a technical spec.

## Knowledge Quality Rules

### Populate EVERY category
After Step 6, every category in the checklist (org:understanding,
org:conventions, project:understanding, project:conventions,
project:decisions, project:domain-rules, project:debugging,
connection:quirks) MUST have at least one entry. If you have no strong
observation for a category, create an initial summary from what you know.

### Entries MUST be descriptive, NEVER prescriptive
State what EXISTS, not what to DO. A future builder agent reads your entries
and makes its own decisions based on its workflow rules.

BAD: "Do not add macro columns unless YML lists them."
BAD: "Always use LEFT JOIN for this table."
GOOD: "Macros produce hour_created_at and normalized_created_at columns."
GOOD: "Sibling models use LEFT JOIN for dim tables."

### NEVER propose negative claims
Do NOT propose entries that say "X is not used" or "no macros needed."
Negative claims mislead future runs into skipping required steps. Only
propose POSITIVE facts you observed and can cite evidence for.

### Every entry must have evidence
Every proposed entry MUST include an EVIDENCE line citing the specific
table, column, query result, or file that supports the claim.
