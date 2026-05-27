# SignalPilot Notebooks — Agent Guide

Write and run SignalPilot notebooks via MCP tools. SignalPilot notebooks are reactive Python notebooks.

---

## MCP Workflow

### Step 1: Find your project

```
list_workspace_projects()
```

Returns project IDs, names, and sources. Pick the `id` you want to work in.

### Step 2: Write and run a notebook

```
run_notebook(
    filename="analysis.py",
    code="<full .py file>",
    project_id="<id from step 1>"
)
```

First call creates an agent branch (`signalpilot-agent/{uuid}`) and a pod. Returns cell outputs, `agent_branch`, and `notebook_url`.

### Step 3: Iterate

Pass `agent_branch` back to reuse the same pod and branch:

```
run_notebook(
    filename="analysis.py",
    code="<updated code>",
    project_id="<same id>",
    agent_branch="signalpilot-agent/a1b2c3d4e5f6"
)
```

Each call commits results to git. The pod persists across calls. Agent branches are local — never pushed to GitHub.

---

## Notebook Format

```python
import signalpilot

__generated_with = "0.13.0"
app = signalpilot.App()


@app.cell
def _():
    import signalpilot as sp
    sp.md("# My Analysis")
    return (sp,)


@app.cell
def _(sp):
    sp.init()
    conn = sp.connect("my_connection")
    df = conn.query("SELECT * FROM orders LIMIT 100")
    df
    return (conn, df,)


@app.cell
def _(df):
    print(f"Rows: {len(df)}")
    print(f"Columns: {list(df.columns)}")
    return ()


if __name__ == "__main__":
    app.run()
```

---

## The Import

```python
import signalpilot as sp
```

## Cell Rules

- Each cell is `@app.cell` — a function that returns a tuple of variables to share
- Variables flow between cells via a reactive DAG — change one cell, dependents re-run
- **One definition per name**: defining `df` in two cells is a hard error
- Use `_` prefix for cell-local temps: `_fig`, `_df` (won't leak)
- Use `print()` for text output — it appears in the MCP agent response
- Last expression in a cell is the cell's visual output

## Output & Markdown

```python
sp.md("# Title")                       # Markdown output
sp.md(f"**{count}** rows found")       # f-string interpolation
_fig                                    # Last expression = cell output
```

## UI Widgets (all reactive)

```python
slider   = sp.ui.slider(start=0, stop=100, value=50, label="X")
dropdown = sp.ui.dropdown(["A", "B", "C"], label="Pick")
text     = sp.ui.text(placeholder="Name")
table    = sp.ui.table(df)              # Interactive data table
explorer = sp.ui.dataframe(df)          # Full filter/sort/search explorer
```

Access values: `slider.value`, `dropdown.value`. Changing a widget re-runs dependent cells.

## Layout

```python
sp.hstack([a, b])                       # Horizontal row
sp.vstack([a, b])                       # Vertical stack
sp.tabs({"Tab 1": a, "Tab 2": b})
sp.callout("Note", kind="info")         # info | warn | danger
```

## State & Caching

```python
get_val, set_val = sp.state(initial_value)

@sp.cache                               # In-memory (session lifetime)
def expensive_fn(): ...

@sp.persistent_cache                    # Disk (survives restarts)
def very_expensive_fn(): ...
```

---

## Data SDK

Governed database access through the SignalPilot gateway. All queries are authenticated, logged, and permissioned. In cloud/MCP mode, `sp.init()` auto-detects the gateway URL and session token — no manual config needed.

### Connections & Queries

```python
sp.init()                               # REQUIRED first
conns = sp.connections()                # List available connections
db = sp.connect("connection_name")      # Get a connection

rows = db.query("SELECT * FROM users LIMIT 10")   # Returns list of dicts
df = pd.DataFrame(db.query("SELECT ..."))          # Convert to DataFrame
```

### Schema Exploration

```python
db.tables()                             # List all tables
db.tables(filter="user")               # Filter by name
db.describe("users")                    # Column details
db.schema_overview()                    # High-level summary
```

### Query Analysis

```python
db.explain("SELECT ...")                # Execution plan
db.sample_values("users", "country")   # Sample distinct values
db.join_path("orders", "customers")    # Find join paths
```

### SQL Cells

```python
result = sp.sql("SELECT * FROM t", engine=db)  # Returns pandas DataFrame
```

---

## Key Rules

1. **`import signalpilot as sp`** — the standard import
2. **`sp.init()` before any data call** — auto-detects credentials in cloud/MCP
3. **One variable per name** — use `_` prefix for cell-local temps
4. **Descriptive global names** — `revenue_df` not `df`
5. **`print()` for agent output** — only printed text appears in MCP responses
6. **dbt owns SQL logic, notebooks visualize** — query built tables, don't rebuild joins in notebooks
7. **Notebooks go in `<project>/notebooks/`** — never in root or `models/`

## Available Packages

The pod has pre-installed: pandas, polars, numpy, duckdb, sqlglot, altair, plotly, matplotlib, seaborn, scikit-learn, scipy, pyarrow, dbt-core, dbt-duckdb, anthropic, openai, mcp.
