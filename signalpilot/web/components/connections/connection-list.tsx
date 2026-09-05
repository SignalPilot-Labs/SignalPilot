"use client";

import { Activity, AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Clock, Copy, Eye, EyeOff, Filter, Loader2, Lock, Pencil, Plus, RefreshCw, Search, Shield, Star, Table2, TestTube, Trash2, XCircle } from "lucide-react";

import { DbTypeIcon } from "./db-type-icon";
import type { ConnectionsController } from "./hooks/use-connections-controller";
import { ConnectionSchemaBrowser, type ConnectionSchemaTable } from "./schema/connection-schema-browser";
import { ConfirmDialog } from "~/components/ui/confirm-dialog";
import { EmptyDatabase, EmptyState } from "~/components/ui/empty-states";
import { MiniBar, Sparkline, StatusDot } from "~/components/ui/data-viz";
import { Tooltip } from "~/components/ui/tooltip";
import { CATEGORY_LABELS, CONNECTOR_TIERS, DB_CONFIGS, DB_TYPE_LABELS as dbTypeLabels } from "~/lib/connections/connector-catalog";
import type { DBType } from "~/lib/types";

interface ConnectionListProps {
  controller: ConnectionsController;
}

export function ConnectionList({ controller }: ConnectionListProps) {
  const {
    connections,
    showForm,
    setShowForm,
    testing,
    testResult,
    expandedConn,
    setExpandedConn,
    schemaData,
    schemaLoading,
    healthData,
    piiData,
    piiLoading,
    piiConfig,
    expandedPiiConn,
    setExpandedPiiConn,
    deleteTarget,
    setDeleteTarget,
    schemaSearch,
    schemaSearchResults,
    schemaSearchLoading,
    endorsements,
    setEndorsements,
    filterTag,
    setFilterTag,
    connectionSearch,
    setConnectionSearch,
    diagnosing,
    diagResults,
    schemaRefreshStatus,
    schemaDiff,
    exploringTable,
    exploredData,
    healthHistory,
    handleEditConnection,
    handleTest,
    handleGenerateSemantic,
    handleDiagnose,
    handleDelete,
    confirmDelete,
    handleClone,
    handleToggleSchema,
    reloadConnectionSchema,
    handleRefreshSchema,
    handleExploreTable,
    handleScanPII,
    handleTogglePII,
    handleSchemaSearch,
  } = controller;

  return (
    <>
      {connections.length === 0 && !showForm ? (
        <EmptyState
          icon={EmptyDatabase}
          title="no connections configured"
          description="add a database connection to enable governed sql queries and sandbox access"
          action={
            <button
              onClick={() => setShowForm(true)}
              className="flex items-center gap-2 px-4 py-2 text-xs text-[var(--color-text-dim)] border border-[var(--color-border)] rounded-[10px] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-colors duration-150"
            >
              <Plus className="w-3.5 h-3.5" /> add first connection
            </button>
          }
        />
      ) : (
        <div className="connection-list" data-tour-id="connection-list">
          <div className="connections-toolbar">
            <label className="connections-search"><Search aria-hidden="true" /><input value={connectionSearch} onChange={(event) => setConnectionSearch(event.target.value)} placeholder="Find a connection" aria-label="Find a connection" /></label>
            {(() => {
              const allTags = [...new Set(connections.flatMap((connection) => connection.tags || []))].sort();
              if (allTags.length === 0) return null;
              return <div className="connections-tags"><span>Tags</span>{allTags.map((tag) => <button key={tag} type="button" className={filterTag === tag ? "is-active" : ""} onClick={() => setFilterTag(filterTag === tag ? null : tag)}>{tag}</button>)}{filterTag && <button type="button" onClick={() => setFilterTag(null)}>Clear</button>}</div>;
            })()}
          </div>
          {connections.filter((connection) => {
            if (filterTag && !(connection.tags || []).includes(filterTag)) return false;
            const needle = connectionSearch.trim().toLowerCase();
            if (!needle) return true;
            return connection.name.toLowerCase().includes(needle)
              || connection.db_type.toLowerCase().includes(needle)
              || (connection.description || "").toLowerCase().includes(needle)
              || (connection.host || "").toLowerCase().includes(needle)
              || (connection.tags || []).some((tag) => tag.toLowerCase().includes(needle));
          }).map((conn) => {
            const health = healthData[conn.name];
            const isExpanded = expandedConn === conn.name;
            const tables = schemaData[conn.name]?.tables;
            const connConfig = DB_CONFIGS[conn.db_type as DBType] || DB_CONFIGS.postgres;

            // Prefer the connection URL when host fields are not available.
            let displayStr = "";
            if (conn.connection_string && !conn.host) {
              try {
                const u = new URL(conn.connection_string.replace(/^(postgresql|postgres|redshift|clickhouse|mysql\+pymysql|mssql|mssql\+pymssql|sqlserver|trino(\+https)?|snowflake|databricks):/, "http:"));
                displayStr = `${u.hostname}${u.port ? `:${u.port}` : ""}${u.pathname !== "/" ? u.pathname : ""}`;
              } catch { displayStr = "(connection string)"; }
            } else if (conn.host && conn.port) {
              displayStr = `${conn.host}:${conn.port}/${conn.database || ""}`;
            } else if (conn.account) {
              displayStr = `${conn.account}/${conn.database || ""}`;
            } else if (conn.project) {
              displayStr = `${conn.project}/${conn.dataset || ""}`;
            } else if (conn.database) {
              displayStr = conn.database;
            }

            return (
              <div key={conn.id} className={`connection-card${isExpanded ? " is-expanded" : ""}`}>
                <div className="connection-card-row">
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
                  <div className="connection-card-info">
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-[var(--color-text)]">{conn.name}</span>
                      <span className="flex items-center gap-1 text-[11px] px-1.5 py-0.5 border border-[var(--color-border)] rounded-[6px] text-[var(--color-text-dim)]">
                        <DbTypeIcon type={conn.db_type} />
                        {dbTypeLabels[conn.db_type] || conn.db_type}
                      </span>
                      <Tooltip content={`Tier ${CONNECTOR_TIERS[conn.db_type as DBType]?.tier || 3}: ${CONNECTOR_TIERS[conn.db_type as DBType]?.tier === 1 ? "Full support" : CONNECTOR_TIERS[conn.db_type as DBType]?.tier === 2 ? "Stable" : "Basic"}`} position="top">
                        <span className={`text-[11px] px-1 py-0.5 border rounded-[6px] cursor-default ${CONNECTOR_TIERS[conn.db_type as DBType]?.color || "text-zinc-400 border-zinc-500/30"}`}>
                          {CONNECTOR_TIERS[conn.db_type as DBType]?.label || "T3"}
                        </span>
                      </Tooltip>
                      <Tooltip content="Credentials encrypted at rest with AES-128 + HMAC-SHA256" position="top">
                        <span className="flex items-center gap-1 text-[11px] px-1 py-0.5 border border-emerald-500/30 rounded-[6px] text-emerald-400/80 cursor-default">
                          <Lock className="w-2.5 h-2.5" strokeWidth={1.5} />
                          encrypted
                        </span>
                      </Tooltip>
                      {conn.byok_key_alias && (
                        <Tooltip content={`Credentials encrypted with your key: ${conn.byok_key_alias}`} position="top">
                          <span className="flex items-center gap-1 text-[11px] px-1 py-0.5 border border-purple-500/30 rounded-[6px] text-purple-400/80 cursor-default">
                            <Shield className="w-2.5 h-2.5" strokeWidth={1.5} />
                            byok
                          </span>
                        </Tooltip>
                      )}
                      {conn.ssl && (
                        <span className="text-[11px] px-1 py-0.5 border border-[var(--color-success)]/30 rounded-[6px] text-[var(--color-success)]">ssl</span>
                      )}
                      {conn.ssh_tunnel?.enabled && (
                        <span className="text-[11px] px-1 py-0.5 border border-purple-500/30 rounded-[6px] text-purple-400">ssh</span>
                      )}
                      {conn.tags?.map((tag) => (
                        <span key={tag} className="text-[11px] px-1 py-0.5 border border-blue-500/30 rounded-[6px] text-blue-400">{tag}</span>
                      ))}
                      {health && (
                        <span className={`text-[12px] ${
                          health.status === "healthy" ? "text-[var(--color-success)]" :
                          health.status === "warning" ? "text-[var(--color-warning)]" :
                          health.status === "degraded" || health.status === "unhealthy" ? "text-[var(--color-error)]" : "text-[var(--color-text-dim)]"
                        }`}>
                          {health.status}
                        </span>
                      )}
                    </div>
                    <div className="connection-card-endpoint">
                      <span className="font-mono">{displayStr}</span>
                      {conn.description && <span className="ml-2 text-[var(--color-text-dim)]">— {conn.description}</span>}
                      {conn.last_used && (
                        <span className="ml-2 text-[var(--color-text-dim)] opacity-60" title={new Date(conn.last_used * 1000).toLocaleString()}>
                          last used {(() => {
                            const diff = Math.floor(Date.now() / 1000 - conn.last_used);
                            if (diff < 60) return "just now";
                            if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
                            if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
                            return `${Math.floor(diff / 86400)}d ago`;
                          })()}
                        </span>
                      )}
                    </div>
                    {health && health.sample_count > 0 && (
                      <div className="connection-card-health">
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
                            <span className="flex items-center gap-1.5 font-mono tabular-nums cursor-default">
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
                          <span className="flex items-center gap-1 font-mono tabular-nums">
                            p95: {health.latency_p95_ms.toFixed(0)}ms
                          </span>
                        )}
                        {healthHistory[conn.name] && healthHistory[conn.name].length >= 2 && (
                          <Tooltip content="latency trend (1h)" position="top">
                            <span className="cursor-default">
                              <Sparkline
                                values={healthHistory[conn.name]}
                                width={48}
                                height={12}
                                color={health.latency_p50_ms != null && health.latency_p50_ms < 50 ? "var(--color-success)" : health.latency_p50_ms != null && health.latency_p50_ms < 150 ? "var(--color-warning)" : "var(--color-text-dim)"}
                                fillOpacity={0.1}
                              />
                            </span>
                          </Tooltip>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Test result — compact summary + expandable detail */}
                  {testResult[conn.name] && (
                    <div className="connection-card-result flex flex-col gap-0.5">
                      <span className={`flex items-center gap-1.5 text-[12px] ${
                        testResult[conn.name].status === "healthy" ? "text-[var(--color-success)]"
                        : testResult[conn.name].status === "warning" ? "text-[var(--color-warning)]"
                        : "text-[var(--color-error)]"
                      }`}>
                        {testResult[conn.name].status === "healthy" ? <CheckCircle2 className="w-3 h-3" />
                         : testResult[conn.name].status === "warning" ? <AlertTriangle className="w-3 h-3" />
                         : <XCircle className="w-3 h-3" />}
                        {testResult[conn.name].phases ? (
                          <span className="flex items-center gap-2">
                            {testResult[conn.name].phases!.map((p, i) => {
                              const phaseLabel = p.phase === "ssh_tunnel" ? "SSH"
                                : p.phase === "schema_access" ? "Schema"
                                : p.phase === "database" ? "Auth"
                                : p.phase;
                              const statusIcon = p.status === "ok" ? "\u2713" : p.status === "warning" ? "!" : "\u2717";
                              const statusColor = p.status === "ok" ? "text-[var(--color-success)]"
                                : p.status === "warning" ? "text-[var(--color-warning)]"
                                : "text-[var(--color-error)]";
                              return (
                                <Tooltip key={i} content={p.message || phaseLabel} position="top">
                                  <span className={`${statusColor} cursor-default font-mono tabular-nums`}>
                                    {phaseLabel}{statusIcon}
                                    {p.duration_ms ? ` ${p.duration_ms}ms` : ""}
                                  </span>
                                </Tooltip>
                              );
                            })}
                            {testResult[conn.name].total_duration_ms != null && (
                              <span className="text-[11px] text-[var(--color-text-dim)] font-mono tabular-nums">
                                total: {testResult[conn.name].total_duration_ms}ms
                              </span>
                            )}
                          </span>
                        ) : (
                          <Tooltip content={testResult[conn.name].message} position="top">
                            <span className="cursor-default">{testResult[conn.name].message.slice(0, 50)}</span>
                          </Tooltip>
                        )}
                      </span>
                    </div>
                  )}

                  {/* Diagnostic results */}
                  {diagResults[conn.name] && (
                    <div className="connection-card-result flex flex-col gap-0.5">
                      <span className="flex items-center gap-2 text-[12px]">
                        {diagResults[conn.name].diagnostics.map((d, i) => {
                          const statusColor = d.status === "ok" ? "text-[var(--color-success)]"
                            : d.status === "warning" ? "text-[var(--color-warning)]"
                            : "text-[var(--color-error)]";
                          const icon = d.status === "ok" ? "\u2713" : d.status === "warning" ? "!" : "\u2717";
                          return (
                            <Tooltip key={i} content={d.hint || d.message} position="top">
                              <span className={`${statusColor} cursor-default font-mono tabular-nums`}>
                                {d.check}{icon} {d.duration_ms}ms
                              </span>
                            </Tooltip>
                          );
                        })}
                      </span>
                    </div>
                  )}

                  {/* Action buttons */}
                  <div className="connection-card-actions">
                    <button onClick={(e) => { e.stopPropagation(); handleToggleSchema(conn.name); }}
                      className="is-primary">
                      {isExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                      <Table2 className="w-3 h-3" strokeWidth={1.5} /> schema
                    </button>
                    <button onClick={(e) => { e.stopPropagation(); const opening = expandedPiiConn !== conn.name; setExpandedPiiConn(opening ? conn.name : null); if (opening) void handleScanPII(conn.name); }} disabled={piiLoading === conn.name}
                      className=""
                      title={piiConfig[conn.name]?.enabled ? "PII redaction active — click to re-scan" : "Scan for PII columns"}
                    >
                      {piiLoading === conn.name ? <Loader2 className="w-3 h-3 animate-spin" /> : <Shield className={`w-3 h-3 ${piiConfig[conn.name]?.enabled ? "text-emerald-400" : ""}`} strokeWidth={1.5} />}
                      pii
                      {piiConfig[conn.name]?.enabled && (
                        <span className="ml-1 px-1 py-0.5 border border-emerald-500/30 rounded-[6px] text-emerald-400 text-[11px]">on</span>
                      )}
                      {!piiConfig[conn.name]?.enabled && piiData[conn.name] && piiData[conn.name].tables_with_pii > 0 && (
                        <span className="ml-1 px-1 py-0.5 border badge-warning rounded-[6px] text-[11px] font-mono tabular-nums">
                          {piiData[conn.name].tables_with_pii}
                        </span>
                      )}
                    </button>
                    <button onClick={() => handleTest(conn.name)} disabled={testing === conn.name}
                      className="is-primary">
                      {testing === conn.name ? <Loader2 className="w-3 h-3 animate-spin" /> : <TestTube className="w-3 h-3" strokeWidth={1.5} />}
                      test
                    </button>
                    <button onClick={() => handleDiagnose(conn.name)} disabled={diagnosing === conn.name}
                      className="">
                      {diagnosing === conn.name ? <Loader2 className="w-3 h-3 animate-spin" /> : <Activity className="w-3 h-3" strokeWidth={1.5} />}
                      diagnose
                    </button>
                    <button onClick={(e) => { e.stopPropagation(); handleEditConnection(conn); }}
                      className="" title="Edit connection" aria-label={`Edit ${conn.name}`}>
                      <Pencil className="w-3 h-3" strokeWidth={1.5} />
                    </button>
                    <button onClick={(e) => { e.stopPropagation(); handleClone(conn.name); }}
                      className="" title="Clone connection" aria-label={`Clone ${conn.name}`}>
                      <Copy className="w-3 h-3" strokeWidth={1.5} />
                    </button>
                    <button onClick={() => handleDelete(conn.name)}
                      className="is-danger" title="Delete connection" aria-label={`Delete ${conn.name}`}>
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                </div>

                {isExpanded && (
                  schemaLoading === conn.name && !tables ? (
                    <div className="connection-schema-empty"><Loader2 className="is-spinning" aria-hidden="true" /><span>Loading schema</span></div>
                  ) : tables && Object.keys(tables).length > 0 ? (
                    <ConnectionSchemaBrowser
                      connectionName={conn.name}
                      defaultDatabaseName={conn.database || conn.catalog || conn.project || undefined}
                      tables={tables as Record<string, ConnectionSchemaTable>}
                      searchTables={schemaSearchResults[conn.name]?.tables as Record<string, ConnectionSchemaTable> | undefined}
                      searchResultCount={schemaSearchResults[conn.name]?.result_count}
                      totalTables={schemaSearchResults[conn.name]?.total_tables}
                      search={schemaSearch[conn.name] || ""}
                      searchLoading={schemaSearchLoading === conn.name}
                      onSearch={(value) => handleSchemaSearch(conn.name, value)}
                      endorsements={endorsements[conn.name] || { endorsed: [], hidden: [], mode: "all" }}
                      onEndorsementsChange={(value) => setEndorsements((prev) => ({ ...prev, [conn.name]: value }))}
                      onReload={() => reloadConnectionSchema(conn.name)}
                      onRefresh={() => handleRefreshSchema(conn.name)}
                      refreshing={schemaLoading === conn.name}
                      refreshStatus={schemaRefreshStatus[conn.name]}
                      schemaChanged={Boolean(schemaDiff[conn.name]?.has_changes)}
                      onGenerateSemantic={() => handleGenerateSemantic(conn.name)}
                      exploringKey={exploringTable}
                      exploredData={exploredData}
                      onExplore={(tableKey) => handleExploreTable(conn.name, tableKey)}
                    />
                  ) : (
                    <div className="connection-schema-empty">No schema available. Test the connection first.</div>
                  )
                )}
                {/* PII Detection Results */}
                {expandedPiiConn === conn.name && (piiConfig[conn.name] || (piiData[conn.name] && piiData[conn.name].tables_with_pii > 0)) && (
                  <div className="connection-pii-panel border-t border-[var(--color-border)] px-4 py-4 animate-fade-in">
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-2">
                        <Shield className={`w-3.5 h-3.5 ${piiConfig[conn.name]?.enabled ? "text-emerald-400" : "text-[var(--color-warning)]"}`} strokeWidth={1.5} />
                        <span className="text-[12px] text-[var(--color-text-muted)]">
                          pii redaction — {Object.keys(piiConfig[conn.name]?.rules || {}).length} columns
                        </span>
                      </div>
                      <button
                        onClick={() => handleTogglePII(conn.name)}
                        className={`px-2.5 py-1 text-[11px] border rounded-[6px] transition-colors duration-150 ${
                          piiConfig[conn.name]?.enabled
                            ? "border-emerald-500/40 text-emerald-400 bg-emerald-500/10 hover:bg-emerald-500/20"
                            : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-text)] hover:text-[var(--color-text)]"
                        }`}
                      >
                        {piiConfig[conn.name]?.enabled ? "redaction on" : "redaction off"}
                      </button>
                    </div>
                    {piiConfig[conn.name]?.rules && Object.keys(piiConfig[conn.name].rules).length > 0 && (
                      <div className="flex flex-wrap gap-2 mb-2">
                        {Object.entries(piiConfig[conn.name].rules).map(([col, rule]) => (
                          <span key={col} className={`text-[11px] px-1.5 py-0.5 border rounded-[6px] tracking-wider uppercase ${
                            rule === "hide" ? "badge-warning" :
                            rule === "hash" ? "border-purple-500/30 text-purple-400" :
                            "badge-warning"
                          }`}>
                            {col} ({rule})
                          </span>
                        ))}
                      </div>
                    )}
                    {piiData[conn.name] && Object.keys(piiData[conn.name].detections).length > 0 && (
                      <div className="space-y-2">
                        {Object.entries(piiData[conn.name].detections).map(([table, columns]) => (
                          <div key={table} className="p-3 border border-[var(--color-warning)]/20 bg-[var(--color-warning)]/5 rounded-[10px]">
                            <p className="text-[12px] text-[var(--color-text-muted)] mb-1.5">{table}</p>
                            <div className="flex flex-wrap gap-2">
                              {Object.entries(columns).map(([col, rule]) => (
                                <span key={col} className={`text-[11px] px-1.5 py-0.5 border rounded-[6px] tracking-wider uppercase ${
                                  rule === "hide" ? "badge-warning" :
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
                    )}
                    <p className="text-[11px] text-[var(--color-text-dim)] mt-2">
                      {piiConfig[conn.name]?.enabled
                        ? "queries will automatically redact flagged columns (hash, mask, or hide)."
                        : "click the toggle to activate automatic pii redaction on query results."}
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
    </>
  );
}
