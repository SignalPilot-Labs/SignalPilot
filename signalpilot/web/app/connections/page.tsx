"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Plus,
  Trash2,
  CheckCircle2,
  XCircle,
  Loader2,
  TestTube,
  ChevronDown,
  ChevronRight,
  Table2,
  Activity,
  AlertTriangle,
  Clock,
  Shield,
  Eye,
} from "lucide-react";
import {
  getConnections,
  createConnection,
  deleteConnection,
  testConnection,
  getConnectionSchema,
  getConnectionsHealth,
  detectPII,
} from "@/lib/api";
import type { ConnectionInfo, ConnectionHealthStats } from "@/lib/types";
import { EmptyDatabase, EmptyState } from "@/components/ui/empty-states";
import { PageHeader, TerminalBar } from "@/components/ui/page-header";
import { StatusDot, MiniBar } from "@/components/ui/data-viz";
import { Tooltip } from "@/components/ui/tooltip";
import { useToast } from "@/components/ui/toast";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";

const dbTypeLabels: Record<string, string> = {
  postgres: "pg",
  duckdb: "duck",
  mysql: "mysql",
  snowflake: "snow",
};

/* ── Database type SVG icons ── */
function DbTypeIcon({ type }: { type: string }) {
  switch (type) {
    case "postgres":
      return (
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
          <ellipse cx="6" cy="3" rx="4.5" ry="2" stroke="currentColor" strokeWidth="0.75" fill="none" />
          <path d="M1.5 3V9C1.5 10.1 3.5 11 6 11C8.5 11 10.5 10.1 10.5 9V3" stroke="currentColor" strokeWidth="0.75" />
          <path d="M1.5 6C1.5 7.1 3.5 8 6 8C8.5 8 10.5 7.1 10.5 6" stroke="currentColor" strokeWidth="0.5" opacity="0.5" />
        </svg>
      );
    case "duckdb":
      return (
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
          <circle cx="6" cy="6" r="4.5" stroke="currentColor" strokeWidth="0.75" fill="none" />
          <circle cx="4.5" cy="5" r="0.8" fill="currentColor" />
          <path d="M4 7.5C4.5 8.5 7.5 8.5 8 7.5" stroke="currentColor" strokeWidth="0.75" strokeLinecap="round" fill="none" />
          <path d="M7.5 4L9 3.5" stroke="currentColor" strokeWidth="0.75" strokeLinecap="round" />
        </svg>
      );
    case "mysql":
      return (
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
          <path d="M2 2L6 10L10 2" stroke="currentColor" strokeWidth="0.75" fill="none" strokeLinecap="round" strokeLinejoin="round" />
          <line x1="4" y1="6" x2="8" y2="6" stroke="currentColor" strokeWidth="0.75" />
        </svg>
      );
    case "snowflake":
      return (
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
          <line x1="6" y1="1" x2="6" y2="11" stroke="currentColor" strokeWidth="0.75" />
          <line x1="1.7" y1="3.5" x2="10.3" y2="8.5" stroke="currentColor" strokeWidth="0.75" />
          <line x1="1.7" y1="8.5" x2="10.3" y2="3.5" stroke="currentColor" strokeWidth="0.75" />
          <circle cx="6" cy="6" r="1.5" stroke="currentColor" strokeWidth="0.5" fill="none" />
        </svg>
      );
    default:
      return (
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
          <rect x="1.5" y="1.5" width="9" height="9" stroke="currentColor" strokeWidth="0.75" fill="none" />
          <circle cx="6" cy="6" r="2" stroke="currentColor" strokeWidth="0.5" fill="none" />
        </svg>
      );
  }
}

export default function ConnectionsPage() {
  const { toast } = useToast();
  const [connections, setConnections] = useState<ConnectionInfo[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<string, { status: string; message: string }>>({});
  const [saving, setSaving] = useState(false);
  const [expandedConn, setExpandedConn] = useState<string | null>(null);
  const [schemaData, setSchemaData] = useState<Record<string, { tables: Record<string, { schema: string; name: string; columns: { name: string; type: string; nullable: boolean; primary_key?: boolean }[] }> }>>({});
  const [schemaLoading, setSchemaLoading] = useState<string | null>(null);
  const [healthData, setHealthData] = useState<Record<string, ConnectionHealthStats>>({});
  const [piiData, setPiiData] = useState<Record<string, { tables_scanned: number; tables_with_pii: number; detections: Record<string, Record<string, string>> }>>({});
  const [piiLoading, setPiiLoading] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [form, setForm] = useState({
    name: "", db_type: "postgres" as const, host: "localhost",
    port: "5432", database: "", username: "", password: "", description: "",
  });

  const refresh = useCallback(() => {
    getConnections().then(setConnections).catch(() => {});
    getConnectionsHealth()
      .then((res) => {
        const map: Record<string, ConnectionHealthStats> = {};
        for (const h of res.connections) map[h.connection_name] = h;
        setHealthData(map);
      })
      .catch(() => {});
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  async function handleCreate() {
    setSaving(true);
    try {
      await createConnection({
        name: form.name, db_type: form.db_type, host: form.host,
        port: parseInt(form.port) || 5432, database: form.database,
        username: form.username, password: form.password, description: form.description,
      });
      setShowForm(false);
      setForm({ name: "", db_type: "postgres", host: "localhost", port: "5432", database: "", username: "", password: "", description: "" });
      refresh();
      toast("connection created successfully", "success");
    } catch (e) { toast(String(e), "error"); } finally { setSaving(false); }
  }

  async function handleTest(name: string) {
    setTesting(name);
    try {
      const result = await testConnection(name);
      setTestResult((prev) => ({ ...prev, [name]: result }));
      toast(result.status === "healthy" ? `${name}: connection healthy` : `${name}: ${result.message}`, result.status === "healthy" ? "success" : "error");
    } catch (e) {
      setTestResult((prev) => ({ ...prev, [name]: { status: "error", message: String(e) } }));
      toast(`${name}: test failed`, "error");
    } finally { setTesting(null); }
  }

  async function handleDelete(name: string) {
    setDeleteTarget(name);
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    await deleteConnection(deleteTarget);
    refresh();
    toast(`${deleteTarget} deleted`, "info");
    setDeleteTarget(null);
  }

  async function handleToggleSchema(name: string) {
    if (expandedConn === name) { setExpandedConn(null); return; }
    setExpandedConn(name);
    if (!schemaData[name]) {
      setSchemaLoading(name);
      try {
        const data = await getConnectionSchema(name);
        setSchemaData((prev) => ({ ...prev, [name]: { tables: data.tables } }));
      } catch { setSchemaData((prev) => ({ ...prev, [name]: { tables: {} } })); }
      finally { setSchemaLoading(null); }
    }
  }

  async function handleScanPII(name: string) {
    setPiiLoading(name);
    try {
      const data = await detectPII(name);
      setPiiData((prev) => ({ ...prev, [name]: data }));
    } catch { setPiiData((prev) => ({ ...prev, [name]: { tables_scanned: 0, tables_with_pii: 0, detections: {} } })); }
    finally { setPiiLoading(null); }
  }

  return (
    <div className="p-8 animate-fade-in">
      <PageHeader
        title="connections"
        subtitle="databases"
        description="manage database connections for governed ai access"
        actions={
          <button
            onClick={() => setShowForm(true)}
            className="flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium tracking-wider uppercase transition-all hover:opacity-90"
          >
            <Plus className="w-3.5 h-3.5" /> add connection
          </button>
        }
      />

      <TerminalBar
        path="connections --list"
        status={<StatusDot status={connections.length > 0 ? "healthy" : "unknown"} size={4} />}
      >
        <div className="flex items-center gap-6 text-xs">
          <span className="text-[var(--color-text-dim)]">registered: <code className="text-[10px] text-[var(--color-text)]">{connections.length}</code></span>
        </div>
      </TerminalBar>

      {/* Create form */}
      {showForm && (
        <div className="mb-6 border border-[var(--color-border)] bg-[var(--color-bg-card)] animate-scale-in overflow-hidden">
          <div className="px-6 py-3 border-b border-[var(--color-border)] flex items-center gap-2">
            <span className="text-[var(--color-text-dim)]"><DbTypeIcon type={form.db_type} /></span>
            <span className="text-[10px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">new connection</span>
          </div>
          <div className="p-6">
            <div className="grid grid-cols-2 gap-4 mb-5">
              {[
                { label: "name", key: "name", placeholder: "prod-analytics", type: "text" },
                { label: "type", key: "db_type", type: "select" },
                { label: "host", key: "host", placeholder: "localhost", type: "text" },
                { label: "port", key: "port", placeholder: "5432", type: "text" },
                { label: "database", key: "database", placeholder: "mydb", type: "text" },
                { label: "username", key: "username", placeholder: "postgres", type: "text" },
                { label: "password", key: "password", type: "password" },
                { label: "description", key: "description", placeholder: "Production analytics DB", type: "text" },
              ].map((field) => (
                <div key={field.key}>
                  <label className="block text-[10px] text-[var(--color-text-dim)] mb-1.5 tracking-wider">{field.label}</label>
                  {field.type === "select" ? (
                    <select
                      value={form.db_type}
                      onChange={(e) => setForm({ ...form, db_type: e.target.value as typeof form.db_type, port: e.target.value === "postgres" ? "5432" : e.target.value === "mysql" ? "3306" : form.port })}
                      className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)]"
                    >
                      <option value="postgres">PostgreSQL</option>
                      <option value="duckdb">DuckDB</option>
                      <option value="mysql">MySQL</option>
                      <option value="snowflake">Snowflake</option>
                    </select>
                  ) : (
                    <input
                      type={field.type}
                      placeholder={field.placeholder}
                      value={form[field.key as keyof typeof form]}
                      onChange={(e) => setForm({ ...form, [field.key]: e.target.value })}
                      className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-xs focus:outline-none focus:border-[var(--color-text-dim)] tracking-wide"
                    />
                  )}
                </div>
              ))}
            </div>
            <div className="flex items-center gap-3">
              <button onClick={handleCreate} disabled={saving || !form.name} className="flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium tracking-wider uppercase transition-all hover:opacity-90 disabled:opacity-30">
                {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                save
              </button>
              <button onClick={() => setShowForm(false)} className="px-4 py-2 text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider">
                cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Connections list */}
      {connections.length === 0 && !showForm ? (
        <EmptyState
          icon={EmptyDatabase}
          title="no connections configured"
          description="add a database connection to enable governed sql queries and sandbox access"
          action={
            <button
              onClick={() => setShowForm(true)}
              className="flex items-center gap-2 px-4 py-2 text-xs text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all tracking-wider"
            >
              <Plus className="w-3.5 h-3.5" /> add first connection
            </button>
          }
        />
      ) : (
        <div className="space-y-2">
          {connections.map((conn) => {
            const health = healthData[conn.name];
            const isExpanded = expandedConn === conn.name;
            const tables = schemaData[conn.name]?.tables;

            return (
              <div key={conn.id} className="bg-[var(--color-bg-card)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] transition-all card-accent-top">
                <div className="flex items-center gap-4 p-4">
                  {/* Status indicator */}
                  <div className="flex-shrink-0">
                    <StatusDot
                      status={
                        health?.status === "healthy" ? "healthy" :
                        health?.status === "warning" ? "warning" :
                        health?.status === "degraded" || health?.status === "unhealthy" ? "error" :
                        "unknown"
                      }
                      size={5}
                      pulse={health?.status === "healthy"}
                    />
                  </div>

                  {/* Connection info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-[var(--color-text)]">{conn.name}</span>
                      <span className="flex items-center gap-1 text-[9px] px-1.5 py-0.5 border border-[var(--color-border)] text-[var(--color-text-dim)] tracking-wider">
                        <DbTypeIcon type={conn.db_type} />
                        {dbTypeLabels[conn.db_type] || conn.db_type}
                      </span>
                      {health && (
                        <span className={`text-[10px] tracking-wider ${
                          health.status === "healthy" ? "text-[var(--color-success)]" :
                          health.status === "warning" ? "text-[var(--color-warning)]" :
                          "text-[var(--color-error)]"
                        }`}>
                          {health.status}
                        </span>
                      )}
                    </div>
                    <div className="text-[10px] text-[var(--color-text-dim)] mt-0.5 tracking-wider">
                      {conn.host}:{conn.port}/{conn.database}
                      {conn.description && <span className="ml-2 text-[var(--color-text-dim)]">— {conn.description}</span>}
                    </div>
                    {health && health.sample_count > 0 && (
                      <div className="flex items-center gap-4 mt-1.5 text-[9px] text-[var(--color-text-dim)] tracking-wider">
                        <span className="flex items-center gap-1">
                          <Activity className="w-2.5 h-2.5" strokeWidth={1.5} />
                          {health.sample_count} queries
                        </span>
                        {health.error_rate != null && health.error_rate > 0 && (
                          <span className="flex items-center gap-1 text-[var(--color-error)]">
                            <AlertTriangle className="w-2.5 h-2.5" strokeWidth={1.5} />
                            {(health.error_rate * 100).toFixed(1)}% errors
                          </span>
                        )}
                        {health.latency_p50_ms != null && (
                          <Tooltip content={`p50: ${health.latency_p50_ms.toFixed(1)}ms${health.latency_p95_ms ? ` · p95: ${health.latency_p95_ms.toFixed(1)}ms` : ""}`} position="top">
                            <span className="flex items-center gap-1.5 tabular-nums cursor-default">
                              <Clock className="w-2.5 h-2.5" strokeWidth={1.5} />
                              <MiniBar
                                value={health.latency_p50_ms}
                                max={300}
                                width={32}
                                height={3}
                                color={health.latency_p50_ms < 50 ? "var(--color-success)" : health.latency_p50_ms < 150 ? "var(--color-warning)" : "var(--color-error)"}
                              />
                              <span className={
                                health.latency_p50_ms < 50 ? "text-[var(--color-success)]" :
                                health.latency_p50_ms < 150 ? "text-[var(--color-text-dim)]" :
                                "text-[var(--color-error)]"
                              }>
                                {health.latency_p50_ms.toFixed(0)}ms
                              </span>
                            </span>
                          </Tooltip>
                        )}
                        {health.latency_p95_ms != null && (
                          <span className="flex items-center gap-1 tabular-nums">
                            p95: {health.latency_p95_ms.toFixed(0)}ms
                          </span>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Test result */}
                  {testResult[conn.name] && (
                    <span className={`flex items-center gap-1 text-[10px] tracking-wider ${testResult[conn.name].status === "healthy" ? "text-[var(--color-success)]" : "text-[var(--color-error)]"}`}>
                      {testResult[conn.name].status === "healthy" ? <CheckCircle2 className="w-3 h-3" /> : <XCircle className="w-3 h-3" />}
                      {testResult[conn.name].message.slice(0, 40)}
                    </span>
                  )}

                  {/* Action buttons */}
                  <div className="flex items-center gap-1">
                    <button onClick={(e) => { e.stopPropagation(); handleToggleSchema(conn.name); }}
                      className="flex items-center gap-1.5 px-2.5 py-1.5 text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)] transition-all tracking-wider">
                      {isExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                      <Table2 className="w-3 h-3" strokeWidth={1.5} /> schema
                    </button>
                    <button onClick={(e) => { e.stopPropagation(); handleScanPII(conn.name); }} disabled={piiLoading === conn.name}
                      className="flex items-center gap-1.5 px-2.5 py-1.5 text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)] transition-all tracking-wider">
                      {piiLoading === conn.name ? <Loader2 className="w-3 h-3 animate-spin" /> : <Eye className="w-3 h-3" strokeWidth={1.5} />}
                      pii
                      {piiData[conn.name] && piiData[conn.name].tables_with_pii > 0 && (
                        <span className="ml-1 px-1 py-0.5 border badge-warning text-[9px] tabular-nums">
                          {piiData[conn.name].tables_with_pii}
                        </span>
                      )}
                    </button>
                    <button onClick={() => handleTest(conn.name)} disabled={testing === conn.name}
                      className="flex items-center gap-1.5 px-2.5 py-1.5 text-[10px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)] transition-all tracking-wider">
                      {testing === conn.name ? <Loader2 className="w-3 h-3 animate-spin" /> : <TestTube className="w-3 h-3" strokeWidth={1.5} />}
                      test
                    </button>
                    <button onClick={() => handleDelete(conn.name)}
                      className="p-1.5 text-[var(--color-text-dim)] hover:text-[var(--color-error)] hover:bg-[var(--color-error)]/5 transition-all">
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                </div>

                {/* Inline schema browser */}
                {isExpanded && (
                  <div className="border-t border-[var(--color-border)] px-4 py-4 animate-fade-in">
                    {schemaLoading === conn.name ? (
                      <div className="flex items-center gap-2 py-4 justify-center text-xs text-[var(--color-text-dim)] tracking-wider">
                        <Loader2 className="w-3.5 h-3.5 animate-spin" /> loading schema...
                      </div>
                    ) : tables && Object.keys(tables).length > 0 ? (
                      <div className="space-y-2">
                        <p className="text-[10px] text-[var(--color-text-dim)] mb-3 tracking-wider">
                          {Object.keys(tables).length} tables
                        </p>
                        <div className="grid grid-cols-2 gap-px max-h-80 overflow-auto bg-[var(--color-border)]">
                          {Object.values(tables).map((t) => (
                            <div key={t.name} className="p-3 bg-[var(--color-bg)]">
                              <div className="flex items-center gap-2 mb-2">
                                <Table2 className="w-3 h-3 text-[var(--color-text-dim)]" strokeWidth={1.5} />
                                <span className="text-[10px] text-[var(--color-text-muted)]">{t.schema}.{t.name}</span>
                                <span className="text-[9px] text-[var(--color-text-dim)] tabular-nums tracking-wider">{t.columns.length} cols</span>
                              </div>
                              <div className="space-y-0.5">
                                {t.columns.slice(0, 8).map((col) => (
                                  <div key={col.name} className="flex items-center gap-2 text-[9px] tracking-wider">
                                    <span className={col.primary_key ? "text-[var(--color-warning)]" : "text-[var(--color-text-dim)]"}>
                                      {col.name}
                                    </span>
                                    <span className="text-[var(--color-text-dim)] opacity-50">{col.type}</span>
                                    {col.primary_key && <span className="text-[var(--color-warning)]">pk</span>}
                                  </div>
                                ))}
                                {t.columns.length > 8 && (
                                  <p className="text-[9px] text-[var(--color-text-dim)] tracking-wider">+ {t.columns.length - 8} more</p>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : (
                      <p className="text-[10px] text-[var(--color-text-dim)] py-4 text-center tracking-wider">
                        no schema available. test the connection first.
                      </p>
                    )}
                  </div>
                )}

                {/* PII Detection Results */}
                {piiData[conn.name] && piiData[conn.name].tables_with_pii > 0 && (
                  <div className="border-t border-[var(--color-border)] px-4 py-4 animate-fade-in">
                    <div className="flex items-center gap-2 mb-3">
                      <Shield className="w-3.5 h-3.5 text-[var(--color-warning)]" strokeWidth={1.5} />
                      <span className="text-[10px] text-[var(--color-text-muted)] tracking-wider">
                        pii detected: {piiData[conn.name].tables_with_pii} table{piiData[conn.name].tables_with_pii > 1 ? "s" : ""}
                      </span>
                    </div>
                    <div className="space-y-2">
                      {Object.entries(piiData[conn.name].detections).map(([table, columns]) => (
                        <div key={table} className="p-3 border border-[var(--color-warning)]/20 bg-[var(--color-warning)]/5">
                          <p className="text-[10px] text-[var(--color-text-muted)] mb-1.5 tracking-wider">{table}</p>
                          <div className="flex flex-wrap gap-2">
                            {Object.entries(columns).map(([col, rule]) => (
                              <span key={col} className={`text-[9px] px-1.5 py-0.5 border tracking-wider uppercase ${
                                rule === "drop" ? "badge-error" :
                                rule === "hash" ? "border-purple-500/30 text-purple-400" :
                                "badge-warning"
                              }`}>
                                {col} ({rule})
                              </span>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                    <p className="text-[9px] text-[var(--color-text-dim)] mt-2 tracking-wider">
                      add these rules to schema.yml annotations for automatic pii redaction.
                    </p>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        title="delete connection"
        message={`Remove "${deleteTarget}" and all associated health data? This cannot be undone.`}
        confirmLabel="delete"
        variant="danger"
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
