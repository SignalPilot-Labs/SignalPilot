"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  ArrowUpRight,
  Check,
  Clock,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  RefreshCw,
  Search,
  Sparkles,
  Star,
  Table2,
} from "lucide-react";
import { setSchemaEndorsements } from "~/lib/api";
import { useConnection } from "~/lib/connection-context";
import { useToast } from "~/components/ui/toast";

export interface ConnectionSchemaTable {
  schema?: string;
  name: string;
  type?: string;
  description?: string;
  row_count?: number;
  columns?: Array<{
    name: string;
    type: string;
    nullable?: boolean;
    primary_key?: boolean;
    comment?: string;
  }>;
  foreign_keys?: Array<{
    column: string;
    references_schema?: string;
    references_table: string;
    references_column: string;
  }>;
  indexes?: unknown[];
  _relevance_score?: number;
  _matched_columns?: string[];
}

interface Endorsements {
  endorsed: string[];
  hidden: string[];
  mode: "all" | "endorsed_only";
}

interface RefreshStatus {
  fingerprint?: string | null;
  last_schema_refresh: number | null;
  cached: boolean;
  cached_table_count: number;
  schema_refresh_interval: number | null;
}

interface ExploredColumn {
  name: string;
  type: string;
  sample_values?: string[];
  value_stats?: { min: unknown; max: unknown; avg: number | null };
}

interface Props {
  connectionName: string;
  tables: Record<string, ConnectionSchemaTable>;
  searchTables?: Record<string, ConnectionSchemaTable>;
  searchResultCount?: number;
  totalTables?: number;
  search: string;
  searchLoading: boolean;
  onSearch: (value: string) => void;
  endorsements: Endorsements;
  onEndorsementsChange: (value: Endorsements) => void;
  onReload: () => Promise<void>;
  onRefresh: () => Promise<void>;
  refreshing: boolean;
  refreshStatus?: RefreshStatus;
  schemaChanged: boolean;
  onGenerateSemantic: () => Promise<void>;
  exploringKey: string | null;
  exploredData: Record<string, { columns: ExploredColumn[] }>;
  onExplore: (tableKey: string) => Promise<void>;
}

function formatRows(value: number | undefined): string {
  if (value == null) return "--";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toLocaleString();
}

function relativeTime(timestamp: number | null | undefined): string {
  if (!timestamp) return "not recorded";
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - timestamp));
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export function ConnectionSchemaBrowser({
  connectionName,
  tables,
  searchTables,
  searchResultCount,
  totalTables,
  search,
  searchLoading,
  onSearch,
  endorsements,
  onEndorsementsChange,
  onReload,
  onRefresh,
  refreshing,
  refreshStatus,
  schemaChanged,
  onGenerateSemantic,
  exploringKey,
  exploredData,
  onExplore,
}: Props) {
  const { setSelectedConn } = useConnection();
  const { toast } = useToast();
  const [selectedKey, setSelectedKey] = useState("");
  const [savingTable, setSavingTable] = useState(false);
  const [semanticLoading, setSemanticLoading] = useState(false);
  const displayTables = searchTables ?? tables;
  const entries = useMemo(
    () => Object.entries(displayTables).sort(([, left], [, right]) => {
      const leftSchema = left.schema || "default";
      const rightSchema = right.schema || "default";
      return leftSchema.localeCompare(rightSchema) || left.name.localeCompare(right.name);
    }),
    [displayTables],
  );

  useEffect(() => {
    if (!selectedKey || !displayTables[selectedKey]) setSelectedKey(entries[0]?.[0] ?? "");
  }, [displayTables, entries, selectedKey]);

  const selectedTable = selectedKey ? displayTables[selectedKey] : undefined;
  const selectedExploredData = selectedKey ? exploredData[`${connectionName}:${selectedKey}`] : undefined;
  const selectedEndorsed = selectedKey ? endorsements.endorsed.includes(selectedKey) : false;
  const selectedHidden = selectedKey ? endorsements.hidden.includes(selectedKey) : false;
  const columnCount = Object.values(displayTables).reduce((sum, table) => sum + (table.columns?.length ?? 0), 0);
  const relationshipCount = Object.values(displayTables).reduce((sum, table) => sum + (table.foreign_keys?.length ?? 0), 0);

  async function saveEndorsements(next: Endorsements) {
    setSavingTable(true);
    try {
      const saved = await setSchemaEndorsements(connectionName, next);
      onEndorsementsChange(saved);
      await onReload();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Could not update schema visibility", "error");
    } finally {
      setSavingTable(false);
    }
  }

  async function toggleSelectedEndorsement() {
    if (!selectedKey || savingTable) return;
    const next: Endorsements = {
      ...endorsements,
      endorsed: selectedEndorsed
        ? endorsements.endorsed.filter((key) => key !== selectedKey)
        : [...endorsements.endorsed.filter((key) => key !== selectedKey), selectedKey],
      hidden: endorsements.hidden.filter((key) => key !== selectedKey),
    };
    await saveEndorsements(next);
  }

  async function toggleSelectedVisibility() {
    if (!selectedKey || savingTable) return;
    const next: Endorsements = {
      ...endorsements,
      hidden: selectedHidden
        ? endorsements.hidden.filter((key) => key !== selectedKey)
        : [...endorsements.hidden.filter((key) => key !== selectedKey), selectedKey],
      endorsed: endorsements.endorsed.filter((key) => key !== selectedKey),
    };
    await saveEndorsements(next);
  }

  async function toggleMode() {
    const mode = endorsements.mode === "all" ? "endorsed_only" : "all";
    await saveEndorsements({ ...endorsements, mode });
    toast(mode === "all" ? "All visible tables are available to agents" : "Only endorsed tables are available to agents", "success");
  }

  async function generateSemantic() {
    setSemanticLoading(true);
    try {
      await onGenerateSemantic();
    } finally {
      setSemanticLoading(false);
    }
  }

  return (
    <section className="connection-schema-workbench">
      <header className="connection-schema-toolbar">
        <div className="connection-schema-summary">
          <span><strong>{searchTables ? searchResultCount ?? entries.length : entries.length}</strong>{searchTables ? ` of ${totalTables ?? Object.keys(tables).length}` : ""} tables</span>
          <span><strong>{columnCount}</strong> columns</span>
          <span><strong>{relationshipCount}</strong> relationships</span>
          {refreshStatus?.fingerprint && <code>#{refreshStatus.fingerprint.slice(0, 8)}</code>}
          <span><Clock /> {relativeTime(refreshStatus?.last_schema_refresh)}</span>
          {schemaChanged && <em>Schema changed</em>}
        </div>
        <div className="connection-schema-actions">
          <button type="button" className={endorsements.mode === "endorsed_only" ? "is-active" : ""} onClick={() => void toggleMode()} disabled={savingTable} title="Change the tables available to agents"><Star />{endorsements.mode === "endorsed_only" ? "Endorsed only" : "All tables"}</button>
          <button type="button" onClick={() => void onRefresh()} disabled={refreshing} title="Refresh schema metadata"><RefreshCw className={refreshing ? "is-spinning" : ""} /><span>Refresh</span></button>
          <button type="button" onClick={() => void generateSemantic()} disabled={semanticLoading} title="Generate semantic metadata">{semanticLoading ? <Loader2 className="is-spinning" /> : <Sparkles />}<span>Semantic</span></button>
          <Link href="/schema" onClick={() => setSelectedConn(connectionName)}>Full explorer <ArrowUpRight /></Link>
        </div>
      </header>

      <div className="connection-schema-grid">
        <aside className="connection-schema-index">
          <label><Search /><input value={search} onChange={(event) => onSearch(event.target.value)} placeholder="Find tables or columns" aria-label="Find tables or columns" />{searchLoading && <Loader2 className="is-spinning" />}</label>
          <nav aria-label={`${connectionName} tables`}>
            {entries.map(([key, table]) => (
              <button key={key} type="button" className={selectedKey === key ? "is-active" : ""} onClick={() => setSelectedKey(key)}>
                <Table2 />
                <span><strong>{table.name}</strong><small>{table.schema || "default"}</small></span>
                <em>{table.columns?.length ?? 0}</em>
                {endorsements.endorsed.includes(key) && <Star className="is-endorsed" aria-label="Endorsed" />}
                {endorsements.hidden.includes(key) && <EyeOff className="is-hidden" aria-label="Hidden from agents" />}
              </button>
            ))}
            {entries.length === 0 && <div className="connection-schema-empty">No matching tables</div>}
          </nav>
        </aside>

        <article className="connection-schema-detail">
          {selectedTable ? (
            <>
              <header>
                <div><span>{selectedTable.schema || "default"}</span><h3>{selectedTable.name}</h3><p>{selectedTable.description || `${selectedTable.type === "view" ? "View" : "Table"} with ${selectedTable.columns?.length ?? 0} columns`}</p></div>
                <dl><div><dt>Rows</dt><dd>{formatRows(selectedTable.row_count)}</dd></div><div><dt>Columns</dt><dd>{selectedTable.columns?.length ?? 0}</dd></div><div><dt>Relations</dt><dd>{selectedTable.foreign_keys?.length ?? 0}</dd></div></dl>
                <div className="connection-schema-table-actions">
                  <button type="button" className={selectedEndorsed ? "is-endorsed" : ""} onClick={() => void toggleSelectedEndorsement()} disabled={savingTable} title={selectedEndorsed ? "Remove endorsement" : "Endorse for agents"}>{savingTable ? <Loader2 className="is-spinning" /> : selectedEndorsed ? <Check /> : <Star />}<span>{selectedEndorsed ? "Endorsed" : "Endorse"}</span></button>
                  <button type="button" className={selectedHidden ? "is-hidden" : ""} onClick={() => void toggleSelectedVisibility()} disabled={savingTable} title={selectedHidden ? "Make visible to agents" : "Hide from agents"}>{selectedHidden ? <Eye /> : <EyeOff />}<span>{selectedHidden ? "Show" : "Hide"}</span></button>
                </div>
              </header>
              <div className="connection-schema-columns">
                <table>
                  <thead><tr><th>Column</th><th>Type</th><th>Null</th><th>Reference</th></tr></thead>
                  <tbody>
                    {(selectedTable.columns ?? []).map((column) => {
                      const foreignKey = selectedTable.foreign_keys?.find((key) => key.column === column.name);
                      const matched = selectedTable._matched_columns?.includes(column.name);
                      return <tr key={column.name} className={matched ? "is-matched" : ""}><td>{column.primary_key && <KeyRound />}<span>{column.name}</span>{column.comment && <small>{column.comment}</small>}</td><td><code>{column.type}</code></td><td>{column.nullable === false ? "No" : "Yes"}</td><td>{foreignKey ? `${foreignKey.references_schema ? `${foreignKey.references_schema}.` : ""}${foreignKey.references_table}.${foreignKey.references_column}` : "--"}</td></tr>;
                    })}
                  </tbody>
                </table>
              </div>
              <footer className="connection-schema-explore">
                <button type="button" onClick={() => void onExplore(selectedKey)} disabled={exploringKey === `${connectionName}:${selectedKey}`}>{exploringKey === `${connectionName}:${selectedKey}` ? <Loader2 className="is-spinning" /> : <Eye />}{selectedExploredData ? "Hide value profile" : "Profile values"}</button>
                {selectedExploredData && <div>{selectedExploredData.columns.slice(0, 8).map((column) => <span key={column.name}><strong>{column.name}</strong>{column.value_stats ? ` ${String(column.value_stats.min)} to ${String(column.value_stats.max)}` : column.sample_values?.length ? ` ${column.sample_values.slice(0, 3).join(", ")}` : " no sample"}</span>)}</div>}
              </footer>
            </>
          ) : <div className="connection-schema-empty">Select a table</div>}
        </article>
      </div>
    </section>
  );
}
