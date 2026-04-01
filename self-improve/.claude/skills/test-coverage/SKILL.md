---
description: "Use when writing tests, improving test coverage, or setting up test infrastructure. Covers testing patterns for the gateway, SQL engine, connectors, and sandbox."
---

# Test Coverage Guide

## Project Test Locations
- Gateway tests: `/workspace/signalpilot/gateway/tests/`
- Sandbox tests: `/workspace/sp-firecracker-vm/test/`

## What to Test (Priority Order)
1. **SQL validation engine** (`gateway/engine/__init__.py`) — the security gatekeeper
   - Blocked statement types (DROP, DELETE, INSERT, etc.)
   - LIMIT injection/clamping
   - Statement stacking detection
   - Comment-based bypass attempts
2. **Gateway endpoints** (`gateway/main.py`) — every route needs coverage
3. **Postgres connector** (`gateway/connectors/postgres.py`) — connection lifecycle
4. **Credential store** (`gateway/store.py`) — vault operations

## Testing Patterns

### Unit Test Template
```python
import pytest
from gateway.engine import validate_sql

def test_blocks_drop_table():
    result = validate_sql("DROP TABLE users")
    assert not result.ok
    assert "blocked" in result.error.lower()

def test_injects_limit():
    result = validate_sql("SELECT * FROM users")
    assert result.ok
    assert "LIMIT" in result.rewritten_sql
```

### Async Test Template
```python
import pytest
import asyncio

@pytest.mark.asyncio
async def test_query_database():
    # Use the actual test databases on ports 5601/5602
    ...
```

### Running Tests
```bash
cd /workspace/signalpilot/gateway
pip install -e ".[dev]" 2>/dev/null || pip install pytest pytest-asyncio
python -m pytest tests/ -v
```

## Rules
- Each test file tests ONE module
- Use descriptive test names: `test_blocks_sql_injection_via_union`
- Test both success AND failure paths
- Don't mock the database — use the real test databases (enterprise-pg:5601, warehouse-pg:5602)
- Commit test files separately from the code they test
