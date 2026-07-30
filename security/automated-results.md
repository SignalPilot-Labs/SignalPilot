# Automated Security Results

Audit date: 2026-07-29

## GitHub security workflow

Run:
[`30467023500`](https://github.com/SignalPilot-Labs/SignalPilot/actions/runs/30467023500)

| Job | Result | Summary |
|---|---|---|
| TruffleHog | Pass | No verified secret reported in the scanned commit range. |
| Semgrep | Pass | Repository security rules completed without a blocking result. |
| Python dependencies | Fail | Gateway lock contains three `mcp` advisories. |
| Node dependencies | Fail | Web lock contains six unaccepted high/critical package findings. |
| Bandit | Fail | Four new B608 findings in the GitHub bot scanner. |
| Security gate | Fail | One or more required jobs failed. |

The workflow stops a dependency job after its first failing project. Local scans were
therefore run for every Python and Node lock to identify findings hidden behind the
first CI failure.

## Python dependency audit

Commands used dependency exports from the checked-in `uv.lock` files and
`pip-audit` against those exports.

### Gateway

Three advisories in `mcp==1.27.1`:

| Advisory | Minimum fixed version |
|---|---|
| PYSEC-2026-3481 | 1.27.2 |
| PYSEC-2026-3482 | 1.27.2 |
| PYSEC-2026-3483 | 1.28.1 |

Upgrade to at least `1.28.1` to resolve all three.

### Notebook server

The local export reported 25 advisory records across four packages. Some records are
duplicate aliases or repeated dependency entries; the affected packages and required
minimums are:

| Package | Locked version | Minimum fixed version |
|---|---:|---:|
| click | 8.2.1 | 8.3.3 |
| mcp | 1.27.1 | 1.28.1 |
| Pillow | 12.2.0 | 12.3.0 |
| pymdown-extensions | 10.21.3 | 11.0.0 |

### Sandbox

No known vulnerability was reported from the exported `sp-sandbox` lock.

## Node dependency audit

Commands used:

```text
npm audit --package-lock-only --omit=dev --json
```

| Project | Critical | High | Moderate | Low | Total |
|---|---:|---:|---:|---:|---:|
| signalpilot/web | 2 | 6 | 5 | 1 | 14 |
| docs | 1 | 6 | 2 | 1 | 10 |

The counts reflect vulnerable package nodes as reported by npm, not unique CVEs.
The web gate currently risk-accepts `form-data` and `request` temporarily, but
`brace-expansion`, `js-yaml`, `next`, `postcss`, `sharp`, and `svgo` remain blocking.

## Static analysis interpretation

The authoritative GitHub Bandit job reports B608 at:

- `signalpilot/gateway/gateway/github_bot/scanner.py:100`
- `signalpilot/gateway/gateway/github_bot/scanner.py:107`
- `signalpilot/gateway/gateway/github_bot/scanner.py:170`
- `signalpilot/gateway/gateway/github_bot/scanner.py:175`

Manual data-flow review found identifier regex validation and identifier quoting on
all four paths. They appear to be false positives, but the required gate is correctly
failing until the code makes that invariant auditable or narrowly suppresses the
rule with regression coverage.

A local Bandit baseline comparison on Windows was not treated as authoritative
because path separators prevented reliable baseline matching. The GitHub Linux job
above is the reproducible result.

## SQL governance probes

The checked-in validation and transform functions were executed against representative
queries with the gateway's locked environment:

| Dialect / input | Observed result |
|---|---|
| DuckDB path-as-table URL | Allowed by `validate_sql` |
| T-SQL `OPENROWSET` | Allowed by `validate_sql` |
| Redshift `dblink` form | Allowed by `validate_sql` |
| PostgreSQL `LIMIT ALL` with maximum 10 | Remained `LIMIT ALL` |
| PostgreSQL `FETCH FIRST 100 ROWS ONLY` with maximum 10 | Remained at 100 |
| T-SQL `TOP 100 PERCENT` with maximum 10 | Correctly rewritten to `TOP 10` |

These probes validate SP-SEC-011 and SP-SEC-012 while avoiding the inaccurate claim
that every T-SQL TOP form bypasses the limiter. No query was sent to a live database.

## Reproduction notes

- Dependency scans used only checked-in lock files; application dependencies were not
  changed.
- Temporary export, audit-cache, and JSON result files were removed after the report
  was written.
- No source, lock, deployment, or credential file was modified as part of this audit.
