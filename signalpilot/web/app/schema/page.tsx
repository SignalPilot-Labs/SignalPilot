"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Braces,
  Check,
  ChevronRight,
  CircleAlert,
  Columns3,
  Copy,
  Database,
  EyeOff,
  HardDrive,
  KeyRound,
  Link2,
  Loader2,
  RefreshCw,
  Rows3,
  ScanSearch,
  Search,
  ShieldCheck,
  ShieldOff,
  Table2,
} from "lucide-react";
import {
  detectPII,
  getConnectionSchema,
  getConnectionSchemaDDL,
  getPIIConfig,
  getSchemaRefreshStatus,
  setPIIConfig,
} from "~/lib/api";
import { useConnection } from "~/lib/connection-context";
import {
  connectionDefaultDatabase,
  groupTablesByDatabase,
  localSchema,
  tableDatabaseKey,
} from "~/lib/schema-databases";
import { EmptyDatabase, EmptyState } from "~/components/ui/empty-states";
import { useToast } from "~/components/ui/toast";
import "./schema.css";

interface ColumnStats {
  distinct_count?: number;
  distinct_fraction?: number;
  data_bytes?: number;
  compressed_bytes?: number;
}

interface Column {
  name: string;
  type: string;
  nullable: boolean;
  primary_key?: boolean;
  comment?: string;
  stats?: ColumnStats;
  encoding?: string;
  dist_key?: boolean;
  sort_key_position?: number;
  low_cardinality?: boolean;
}

interface ForeignKey {
  column: string;
  references_table: string;
  references_column: string;
  references_schema?: string;
}

interface TableSchema {
  schema: string;
  name: string;
  database?: string;
  columns: Column[];
  foreign_keys?: ForeignKey[];
  row_count?: number;
  description?: string;
  engine?: string;
  sorting_key?: string;
  diststyle?: string;
  sortkey?: string;
  clustering_key?: string;
  size_mb?: number;
  total_bytes?: number;
}

interface SchemaData {
  connection_name: string;
  db_type: string;
  table_count: number;
  total_tables?: number;
  tables: Record<string, TableSchema>;
}

interface PIIConfig {
  enabled: boolean;
  rules: Record<string, string>;
}

type ViewMode = "columns" | "ddl";

const EMPTY_PII_CONFIG: PIIConfig = { enabled: false, rules: {} };

function formatCount(value: number | undefined): string {
  if (value == null) return "--";
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)}B`;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toLocaleString();
}

function formatBytes(table: TableSchema): string {
  const bytes = table.total_bytes ?? (table.size_mb == null ? undefined : table.size_mb * 1_048_576);
  if (bytes == null) return "--";
  if (bytes >= 1_073_741_824) return `${(bytes / 1_073_741_824).toFixed(1)} GB`;
  if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`;
  if (bytes >= 1_024) return `${(bytes / 1_024).toFixed(1)} KB`;
  return `${bytes.toFixed(0)} B`;
}

function formatCardinality(stats: ColumnStats | undefined): string {
  if (!stats) return "--";
  if (stats.distinct_count != null) return formatCount(stats.distinct_count);
  if (stats.distinct_fraction != null) return `${(stats.distinct_fraction * 100).toFixed(1)}%`;
  return "--";
}

function typeFamily(type: string): string {
  const normalized = type.toLowerCase();
  if (/int|serial/.test(normalized)) return "integer";
  if (/numeric|decimal|real|double|float/.test(normalized)) return "number";
  if (/char|text|string/.test(normalized)) return "text";
  if (/date|time/.test(normalized)) return "time";
  if (/bool/.test(normalized)) return "boolean";
  if (/json|variant|struct|array|map/.test(normalized)) return "structured";
  return "other";
}

function findRule(rules: Record<string, string>, column: string): [string, string] | null {
  const normalized = column.toLowerCase();
  for (const [key, rule] of Object.entries(rules)) {
    if (key.toLowerCase() === normalized) return [key, rule];
  }
  return null;
}

function tableIdentity(key: string, table: TableSchema): string {
  return table.schema ? `${table.schema}.${table.name}` : key;
}

export default function SchemaExplorerPage() {
  const { connections, selectedConn, setSelectedConn } = useConnection();
  const { toast } = useToast();
  const [schema, setSchema] = useState<SchemaData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedDatabase, setSelectedDatabase] = useState<string | null>(null);
  const [databaseSearch, setDatabaseSearch] = useState("");
  const [selectedTableKey, setSelectedTableKey] = useState("");
  const [search, setSearch] = useState("");
  const [columnSearch, setColumnSearch] = useState("");
  const [schemaFilter, setSchemaFilter] = useState("all");
  const [viewMode, setViewMode] = useState<ViewMode>("columns");
  const [piiConfig, setPiiConfigState] = useState<PIIConfig>(EMPTY_PII_CONFIG);
  const [piiDetections, setPiiDetections] = useState<Record<string, Record<string, string>>>({});
  const [scanningPii, setScanningPii] = useState(false);
  const [savingColumn, setSavingColumn] = useState<string | null>(null);
  const [savingEnabled, setSavingEnabled] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<number | null>(null);
  const [refreshInterval, setRefreshInterval] = useState<number | null>(null);
  const [ddlContent, setDdlContent] = useState("");
  const [ddlLoading, setDdlLoading] = useState(false);
  const [ddlTokens, setDdlTokens] = useState(0);
  const [copied, setCopied] = useState(false);

  const loadSchema = useCallback(async () => {
    if (!selectedConn) return;
    setLoading(true);
    setError(null);
    try {
      const [schemaData, config] = await Promise.all([
        getConnectionSchema(selectedConn) as Promise<SchemaData>,
        getPIIConfig(selectedConn),
      ]);
      setSchema(schemaData);
      setPiiConfigState(config);
      // Suggestions are session-scoped review flags — a refresh clears them.
      setPiiDetections({});
      const keys = Object.keys(schemaData.tables).sort((left, right) => left.localeCompare(right));
      setSelectedTableKey((current) => current && schemaData.tables[current] ? current : keys[0] ?? "");
      const status = await getSchemaRefreshStatus(selectedConn).catch(() => null);
      setLastRefresh(status?.last_schema_refresh ?? null);
      setRefreshInterval(status?.schema_refresh_interval ?? null);
    } catch (loadError) {
      setSchema(null);
      setError(loadError instanceof Error ? loadError.message : String(loadError));
    } finally {
      setLoading(false);
    }
  }, [selectedConn]);

  const loadDDL = useCallback(async () => {
    if (!selectedConn || !schema) return;
    setDdlLoading(true);
    try {
      const data = await getConnectionSchemaDDL(selectedConn, Math.min(schema.table_count, 500));
      setDdlContent(data.ddl);
      setDdlTokens(data.token_estimate);
    } catch (ddlError) {
      setDdlContent("-- DDL unavailable");
      toast(ddlError instanceof Error ? ddlError.message : "Could not load DDL", "error");
    } finally {
      setDdlLoading(false);
    }
  }, [schema, selectedConn, toast]);

  useEffect(() => {
    setSchema(null);
    setSelectedDatabase(null);
    setDatabaseSearch("");
    setSelectedTableKey("");
    setSchemaFilter("all");
    setSearch("");
    setColumnSearch("");
    setPiiConfigState(EMPTY_PII_CONFIG);
    setPiiDetections({});
    setDdlContent("");
    setDdlTokens(0);
    if (selectedConn) void loadSchema();
  }, [selectedConn, loadSchema]);

  useEffect(() => {
    if (viewMode === "ddl" && schema && !ddlContent) void loadDDL();
  }, [ddlContent, loadDDL, schema, viewMode]);

  const tables = useMemo(
    () => schema ? Object.entries(schema.tables).sort(([, left], [, right]) => {
      const schemaOrder = (left.schema || "default").localeCompare(right.schema || "default");
      return schemaOrder || left.name.localeCompare(right.name);
    }) : [],
    [schema],
  );

  const fallbackDb = useMemo(
    () => connectionDefaultDatabase(connections.find((connection) => connection.name === selectedConn)),
    [connections, selectedConn],
  );

  const databaseGroups = useMemo(
    () => groupTablesByDatabase(schema?.tables ?? {}, fallbackDb),
    [fallbackDb, schema],
  );

  const filteredDatabaseGroups = useMemo(() => {
    const needle = databaseSearch.trim().toLowerCase();
    return needle ? databaseGroups.filter((group) => group.name.toLowerCase().includes(needle)) : databaseGroups;
  }, [databaseGroups, databaseSearch]);

  const dbTables = useMemo(
    () => selectedDatabase
      ? tables.filter(([, table]) => tableDatabaseKey(table, fallbackDb) === selectedDatabase)
      : [],
    [fallbackDb, selectedDatabase, tables],
  );

  const schemaGroups = useMemo(() => {
    const counts = new Map<string, number>();
    for (const [, table] of dbTables) {
      const group = localSchema(table);
      counts.set(group, (counts.get(group) ?? 0) + 1);
    }
    return [...counts.entries()].sort(([left], [right]) => left.localeCompare(right));
  }, [dbTables]);

  const filteredTables = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return dbTables.filter(([key, table]) => {
      if (schemaFilter !== "all" && localSchema(table) !== schemaFilter) return false;
      if (!needle) return true;
      return key.toLowerCase().includes(needle)
        || table.name.toLowerCase().includes(needle)
        || table.columns.some((column) => column.name.toLowerCase().includes(needle));
    });
  }, [dbTables, schemaFilter, search]);

  const openDatabase = useCallback((name: string) => {
    setSelectedDatabase(name);
    setSchemaFilter("all");
    setSearch("");
    setColumnSearch("");
    if (schema) {
      const first = Object.entries(schema.tables)
        .filter(([, table]) => tableDatabaseKey(table, fallbackDb) === name)
        .sort(([left], [right]) => left.localeCompare(right))[0];
      setSelectedTableKey(first?.[0] ?? "");
    }
  }, [fallbackDb, schema]);

  const selectedTable = selectedTableKey ? schema?.tables[selectedTableKey] ?? null : null;
  const selectedColumns = useMemo(() => {
    if (!selectedTable) return [];
    const needle = columnSearch.trim().toLowerCase();
    return needle
      ? selectedTable.columns.filter((column) => column.name.toLowerCase().includes(needle) || column.type.toLowerCase().includes(needle))
      : selectedTable.columns;
  }, [columnSearch, selectedTable]);

  const totalColumns = useMemo(
    () => tables.reduce((sum, [, table]) => sum + table.columns.length, 0),
    [tables],
  );
  const protectedColumns = Object.keys(piiConfig.rules).length;

  const suggestionFor = useCallback((table: TableSchema, column: string): string | null => {
    const tableNames = [table.name, table.schema ? `${table.schema}.${table.name}` : table.name];
    for (const name of tableNames) {
      const detections = piiDetections[name];
      if (!detections) continue;
      const match = Object.entries(detections).find(([candidate]) => candidate.toLowerCase() === column.toLowerCase());
      if (match) return match[1];
    }
    return null;
  }, [piiDetections]);

  async function scanPii() {
    if (!selectedConn) return;
    setScanningPii(true);
    try {
      const result = await detectPII(selectedConn);
      setPiiDetections(result.detections);
      const count = Object.values(result.detections).reduce((sum, columns) => sum + Object.keys(columns).length, 0);
      toast(count ? `${count} sensitive columns found for review` : "No likely PII columns found", "info");
    } catch (scanError) {
      toast(scanError instanceof Error ? scanError.message : "PII scan failed", "error");
    } finally {
      setScanningPii(false);
    }
  }

  async function toggleColumnProtection(column: Column) {
    if (!selectedConn || savingColumn) return;
    const previous = piiConfig;
    const nextRules = { ...previous.rules };
    const existing = findRule(nextRules, column.name);
    if (existing) delete nextRules[existing[0]];
    if (existing?.[1] !== "hide") nextRules[column.name] = "hide";
    const next = { enabled: Object.keys(nextRules).length > 0, rules: nextRules };
    setSavingColumn(column.name);
    setPiiConfigState(next);
    try {
      const saved = await setPIIConfig(selectedConn, next);
      setPiiConfigState(saved);
      toast(existing?.[1] === "hide" ? `${column.name} is no longer hidden` : `${column.name} is hidden in query results`, "success");
    } catch (saveError) {
      setPiiConfigState(previous);
      toast(saveError instanceof Error ? saveError.message : "Could not save PII protection", "error");
    } finally {
      setSavingColumn(null);
    }
  }

  async function toggleProtectionEnabled() {
    if (!selectedConn || savingEnabled) return;
    const previous = piiConfig;
    const next = { ...previous, enabled: !previous.enabled };
    setSavingEnabled(true);
    setPiiConfigState(next);
    try {
      const saved = await setPIIConfig(selectedConn, next);
      setPiiConfigState(saved);
      toast(`PII protection ${saved.enabled ? "enabled" : "paused"}`, saved.enabled ? "success" : "info");
    } catch (saveError) {
      setPiiConfigState(previous);
      toast(saveError instanceof Error ? saveError.message : "Could not update PII protection", "error");
    } finally {
      setSavingEnabled(false);
    }
  }

  async function copyDDL() {
    if (!ddlContent) return;
    await navigator.clipboard.writeText(ddlContent);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }

  return (
    <main className="schema-page">
      <header className="schema-titlebar">
        <div>
          <span className="schema-eyebrow">Database catalog</span>
          <h1>Schema</h1>
          <p>Inspect warehouse structure and govern sensitive result fields.</p>
        </div>
        <div className="schema-title-actions">
          <label className="schema-connection-select">
            <Database aria-hidden="true" />
            <select value={selectedConn} onChange={(event) => setSelectedConn(event.target.value)} aria-label="Database connection">
              {connections.length === 0 && <option value="">No connections</option>}
              {connections.map((connection) => <option key={connection.name} value={connection.name}>{connection.name} ({connection.db_type})</option>)}
            </select>
          </label>
          <button className="schema-icon-button" type="button" onClick={() => void loadSchema()} disabled={!selectedConn || loading} title="Refresh schema" aria-label="Refresh schema">
            <RefreshCw className={loading ? "is-spinning" : ""} aria-hidden="true" />
          </button>
        </div>
      </header>

      {schema && (
        <section className="schema-statusbar" aria-label="Schema summary">
          <span><i className="schema-live-dot" /> {selectedConn}</span>
          <span><strong>{databaseGroups.length.toLocaleString()}</strong> databases</span>
          <span><strong>{schema.table_count.toLocaleString()}</strong> tables</span>
          <span><strong>{totalColumns.toLocaleString()}</strong> columns</span>
          <span><strong>{databaseGroups.reduce((sum, group) => sum + group.schemaCount, 0).toLocaleString()}</strong> schemas</span>
          <span><strong>{protectedColumns.toLocaleString()}</strong> protected</span>
          <span className="schema-statusbar-tail">{schema.db_type}{lastRefresh ? ` / refreshed ${new Date(lastRefresh * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : ""}{refreshInterval ? ` / every ${refreshInterval >= 3600 ? `${Math.round(refreshInterval / 3600)}h` : `${Math.round(refreshInterval / 60)}m`}` : ""}</span>
        </section>
      )}

      {error && <div className="schema-error"><CircleAlert aria-hidden="true" /><span>{error}</span></div>}

      {loading && !schema && (
        <div className="schema-loading"><Loader2 className="is-spinning" aria-hidden="true" /><span>Loading schema</span></div>
      )}

      {!loading && !schema && !error && (
        <EmptyState icon={EmptyDatabase} title="Select a connection" description="Choose a database connection to inspect its schema." />
      )}

      {schema && !selectedDatabase && (
        <section className="schema-db-picker" aria-label="Choose a database">
          <header className="schema-db-picker-head">
            <div>
              <h2>Choose a database</h2>
              <p>{databaseGroups.length === 1 ? "This connection exposes one database" : `This connection exposes ${databaseGroups.length} databases`} — pick one to explore its schemas and tables.</p>
            </div>
            {databaseGroups.length > 6 && (
              <label className="schema-db-search">
                <Search aria-hidden="true" />
                <input value={databaseSearch} onChange={(event) => setDatabaseSearch(event.target.value)} placeholder="Filter databases" aria-label="Filter databases" />
              </label>
            )}
          </header>
          <div className="schema-db-grid">
            {filteredDatabaseGroups.map((group) => (
              <button key={group.name} type="button" className="schema-db-card" onClick={() => openDatabase(group.name)}>
                <span className="schema-db-card-title"><Database aria-hidden="true" /><strong>{group.name}</strong><ChevronRight aria-hidden="true" /></span>
                <dl>
                  <div><dt>Tables</dt><dd>{group.tableCount.toLocaleString()}</dd></div>
                  <div><dt>Schemas</dt><dd>{group.schemaCount.toLocaleString()}</dd></div>
                  <div><dt>Rows</dt><dd>{formatCount(group.rowCount)}</dd></div>
                </dl>
              </button>
            ))}
            {filteredDatabaseGroups.length === 0 && <div className="schema-no-results">No matching databases</div>}
          </div>
        </section>
      )}

      {schema && selectedDatabase && (
        <>
        <div className="schema-db-breadcrumb">
          <button type="button" className="schema-db-back" onClick={() => { setSelectedDatabase(null); setSelectedTableKey(""); }}>
            <ArrowLeft aria-hidden="true" /> Databases
          </button>
          <ChevronRight aria-hidden="true" className="schema-db-crumb-sep" />
          <div className="schema-db-strip" role="tablist" aria-label="Switch database">
            {databaseGroups.map((group) => (
              <button key={group.name} type="button" role="tab" aria-selected={group.name === selectedDatabase} className={group.name === selectedDatabase ? "is-active" : ""} onClick={() => openDatabase(group.name)}>
                <Database aria-hidden="true" />{group.name} <span>{group.tableCount}</span>
              </button>
            ))}
          </div>
        </div>
        <section className="schema-workbench">
          <aside className="schema-object-browser">
            <div className="schema-pane-heading"><div><span>Objects</span><strong>{filteredTables.length.toLocaleString()}</strong></div></div>
            <label className="schema-search">
              <Search aria-hidden="true" />
              <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Find tables or columns" aria-label="Find tables or columns" />
            </label>
            <div className="schema-filter-strip" role="tablist" aria-label="Filter by schema">
              <button type="button" className={schemaFilter === "all" ? "is-active" : ""} onClick={() => setSchemaFilter("all")}>All <span>{dbTables.length}</span></button>
              {schemaGroups.map(([group, count]) => (
                <button key={group} type="button" className={schemaFilter === group ? "is-active" : ""} onClick={() => setSchemaFilter(group)}>{group} <span>{count}</span></button>
              ))}
            </div>
            <nav className="schema-table-list" aria-label="Database tables">
              {filteredTables.length === 0 && <div className="schema-no-results">No matching tables</div>}
              {filteredTables.map(([key, table]) => {
                const active = selectedTableKey === key;
                const protectedCount = table.columns.filter((column) => findRule(piiConfig.rules, column.name)).length;
                const pendingCount = table.columns.filter((column) => !findRule(piiConfig.rules, column.name) && suggestionFor(table, column.name)).length;
                return (
                  <button key={key} type="button" className={`schema-table-item${active ? " is-active" : ""}`} onClick={() => { setSelectedTableKey(key); setColumnSearch(""); setViewMode("columns"); }}>
                    <Table2 aria-hidden="true" />
                    <span><strong>{table.name}</strong><small>{localSchema(table)}</small></span>
                    <em>{table.columns.length}</em>
                    <i className="schema-table-flags">
                      {pendingCount > 0 && <AlertTriangle className="is-pending" aria-label={`${pendingCount} suggested PII columns need a decision`} />}
                      {protectedCount > 0 && <ShieldCheck className="is-protected" aria-label={`${protectedCount} protected columns`} />}
                    </i>
                    <ChevronRight aria-hidden="true" />
                  </button>
                );
              })}
            </nav>
          </aside>

          <section className="schema-detail-pane">
            {selectedTable ? (
              <>
                <header className="schema-table-header">
                  <div className="schema-table-identity">
                    <span>{selectedDatabase ? `${selectedDatabase} / ${localSchema(selectedTable)}` : localSchema(selectedTable)}</span>
                    <h2>{selectedTable.name}</h2>
                    {selectedTable.description && <p>{selectedTable.description}</p>}
                  </div>
                  <div className="schema-table-metrics">
                    <div><Rows3 aria-hidden="true" /><span>Rows</span><strong>{formatCount(selectedTable.row_count)}</strong></div>
                    <div><Columns3 aria-hidden="true" /><span>Columns</span><strong>{selectedTable.columns.length}</strong></div>
                    <div><Link2 aria-hidden="true" /><span>Relations</span><strong>{selectedTable.foreign_keys?.length ?? 0}</strong></div>
                    <div><HardDrive aria-hidden="true" /><span>Storage</span><strong>{formatBytes(selectedTable)}</strong></div>
                  </div>
                </header>

                <div className="schema-detail-toolbar">
                  <div className="schema-view-tabs" role="tablist" aria-label="Schema view">
                    <button type="button" role="tab" aria-selected={viewMode === "columns"} className={viewMode === "columns" ? "is-active" : ""} onClick={() => setViewMode("columns")}><Columns3 aria-hidden="true" /> Columns</button>
                    <button type="button" role="tab" aria-selected={viewMode === "ddl"} className={viewMode === "ddl" ? "is-active" : ""} onClick={() => setViewMode("ddl")}><Braces aria-hidden="true" /> DDL</button>
                  </div>
                  {viewMode === "columns" ? (
                    <label className="schema-column-search"><Search aria-hidden="true" /><input value={columnSearch} onChange={(event) => setColumnSearch(event.target.value)} placeholder="Filter columns" aria-label="Filter columns" /></label>
                  ) : (
                    <button type="button" className="schema-copy-button" onClick={() => void copyDDL()} disabled={!ddlContent}><span>{ddlTokens ? `~${ddlTokens.toLocaleString()} tokens` : ""}</span>{copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}{copied ? "Copied" : "Copy"}</button>
                  )}
                </div>

                {viewMode === "columns" ? (
                  <div className="schema-columns-scroll">
                    <table className="schema-columns-table">
                      <thead><tr><th>Column</th><th>Type</th><th>Null</th><th>Cardinality</th><th>Reference</th><th>Protection</th></tr></thead>
                      <tbody>
                        {selectedColumns.map((column) => {
                          const currentRule = findRule(piiConfig.rules, column.name)?.[1] ?? null;
                          const suggestion = suggestionFor(selectedTable, column.name);
                          const foreignKey = selectedTable.foreign_keys?.find((key) => key.column === column.name);
                          const saving = savingColumn?.toLowerCase() === column.name.toLowerCase();
                          return (
                            <tr
                              key={column.name}
                              className={`${currentRule === "hide" && piiConfig.enabled ? "is-protected" : ""}${saving ? " is-saving" : ""}`}
                              onClick={() => void toggleColumnProtection(column)}
                              onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); void toggleColumnProtection(column); } }}
                              tabIndex={0}
                              role="button"
                              aria-label={`${currentRule === "hide" ? "Remove protection from" : "Hide"} ${column.name}`}
                            >
                              <td><span className="schema-column-name">{column.primary_key && <KeyRound aria-label="Primary key" />}{column.name}</span>{column.comment && <small>{column.comment}</small>}</td>
                              <td><span className="schema-type" data-family={typeFamily(column.type)}><i />{column.type}</span>{column.encoding && column.encoding !== "none" && <small>{column.encoding}</small>}</td>
                              <td>{column.nullable ? <span className="schema-muted">Yes</span> : <strong>No</strong>}</td>
                              <td className="schema-mono">{formatCardinality(column.stats)}</td>
                              <td>{foreignKey ? <span className="schema-reference">{foreignKey.references_schema ? `${foreignKey.references_schema}.` : ""}{foreignKey.references_table}.{foreignKey.references_column}</span> : <span className="schema-muted">--</span>}</td>
                              <td>
                                {saving ? <span className="schema-protection is-saving"><Loader2 className="is-spinning" /> Saving</span>
                                  : currentRule ? <span className={`schema-protection is-${currentRule}`}>{currentRule === "hide" ? <EyeOff /> : <ShieldCheck />}{currentRule === "hide" ? (piiConfig.enabled ? "Hidden" : "Paused") : currentRule}</span>
                                    : suggestion ? <span className="schema-protection is-suggested"><ScanSearch /> Suggested</span>
                                      : <span className="schema-protection"><ShieldOff /> None</span>}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                    {selectedColumns.length === 0 && <div className="schema-no-results">No matching columns</div>}
                  </div>
                ) : (
                  <div className="schema-ddl">
                    {ddlLoading ? <div className="schema-loading"><Loader2 className="is-spinning" /><span>Loading DDL</span></div> : <pre>{ddlContent || "-- No DDL available"}</pre>}
                  </div>
                )}
              </>
            ) : <div className="schema-no-selection"><Table2 /><span>Select a table</span></div>}
          </section>

          <aside className="schema-governance-pane">
            <div className="schema-pane-heading"><div><span>Governance</span><strong>{protectedColumns}</strong></div></div>
            <section className="schema-protection-summary">
              <div className={piiConfig.enabled ? "is-enabled" : ""}><ShieldCheck aria-hidden="true" /><span><strong>Result protection</strong><small>{piiConfig.enabled ? "Active" : "Paused"}</small></span></div>
              <button type="button" className={`schema-switch${piiConfig.enabled ? " is-on" : ""}`} onClick={() => void toggleProtectionEnabled()} disabled={savingEnabled} role="switch" aria-checked={piiConfig.enabled} aria-label="Toggle PII result protection"><i /></button>
            </section>
            <dl className="schema-governance-stats">
              <div><dt>Hidden fields</dt><dd>{Object.values(piiConfig.rules).filter((rule) => rule === "hide").length}</dd></div>
              <div><dt>Other rules</dt><dd>{Object.values(piiConfig.rules).filter((rule) => rule !== "hide").length}</dd></div>
              <div><dt>Suggestions</dt><dd>{Object.values(piiDetections).reduce((sum, columns) => sum + Object.keys(columns).length, 0)}</dd></div>
            </dl>
            <button type="button" className="schema-scan-button" onClick={() => void scanPii()} disabled={scanningPii}>
              {scanningPii ? <Loader2 className="is-spinning" aria-hidden="true" /> : <ScanSearch aria-hidden="true" />}
              Scan for sensitive fields
            </button>
            <section className="schema-rule-list">
              <header><span>Saved rules</span><small>{piiConfig.enabled ? "Enforced" : "Not enforced"}</small></header>
              {Object.keys(piiConfig.rules).length === 0 ? (
                <div className="schema-empty-rules"><ShieldOff aria-hidden="true" /><span>No protected fields</span></div>
              ) : (
                Object.entries(piiConfig.rules).sort(([left], [right]) => left.localeCompare(right)).map(([column, rule]) => (
                  <button key={column} type="button" onClick={() => {
                    const tableWithColumn = tables.find(([, table]) => table.columns.some((candidate) => candidate.name.toLowerCase() === column.toLowerCase()));
                    if (tableWithColumn) { setSelectedDatabase(tableDatabaseKey(tableWithColumn[1], fallbackDb)); setSelectedTableKey(tableWithColumn[0]); setViewMode("columns"); setColumnSearch(column); }
                  }}>
                    <span><strong>{column}</strong><small>query result field</small></span><em className={`is-${rule}`}>{rule}</em>
                  </button>
                ))
              )}
            </section>
            {selectedTable && (
              <section className="schema-table-properties">
                <header>Table properties</header>
                <dl>
                  <div><dt>Identity</dt><dd>{tableIdentity(selectedTableKey, selectedTable)}</dd></div>
                  {selectedTable.engine && <div><dt>Engine</dt><dd>{selectedTable.engine}</dd></div>}
                  {selectedTable.diststyle && <div><dt>Distribution</dt><dd>{selectedTable.diststyle}</dd></div>}
                  {(selectedTable.sortkey || selectedTable.sorting_key) && <div><dt>Sort key</dt><dd>{selectedTable.sortkey || selectedTable.sorting_key}</dd></div>}
                  {selectedTable.clustering_key && <div><dt>Cluster key</dt><dd>{selectedTable.clustering_key}</dd></div>}
                </dl>
              </section>
            )}
          </aside>
        </section>
        </>
      )}
    </main>
  );
}
