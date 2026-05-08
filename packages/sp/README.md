# signalpilot-sp

SignalPilot SDK — governed data access for notebooks and scripts.

## Install

```bash
pip install signalpilot-sp
```

## Quick Start

### Local (no auth needed)

```python
import sp

sp.init()
db = sp.connect("default")
rows = db.query("SELECT * FROM users LIMIT 10")
```

### Cloud

```python
import sp

sp.init(api_key="sp_...")  # or set SP_API_KEY env var
db = sp.connect("analytics")
rows = db.query("SELECT * FROM users LIMIT 10")
```

## Available Connections

```python
sp.init()
print(sp.connections())  # ["default", "analytics", ...]
```

## Connection Methods

```python
db = sp.connect("default")

# Execute a governed SQL query
rows = db.query("SELECT * FROM orders WHERE amount > 100", row_limit=500)

# List tables
tables = db.tables()

# Describe a table (columns, types, stats)
columns = db.describe("users")

# Query plan and cost estimate
plan = db.explain("SELECT * FROM orders JOIN users ON orders.user_id = users.id")

# Sample distinct values for a column
values = db.sample_values("orders", "status")

# Find join path between two tables
path = db.join_path("orders", "users")

# High-level schema summary
overview = db.schema_overview()
```

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `SP_GATEWAY_URL` | Gateway URL (default: `http://localhost:3300`) |
| `SP_API_KEY` | API key for cloud gateway (same key used for MCP) |
