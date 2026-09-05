"use client";

import { useCallback, useEffect, useRef, useState, type ChangeEvent } from "react";

import {
  createConnection, updateConnection, deleteConnection, cloneConnection,
  testConnection, getConnectionSchema, searchConnectionSchema, detectPII,
  setPIIConfig, detectAndSavePII, refreshConnectionSchema,
  getSchemaEndorsements, exportConnections, importConnections, getNetworkInfo,
  diagnoseConnection, generateSemanticModel, testCredentials,
  getSchemaRefreshStatus, getConnectionSchemaDiff, exploreColumns,
  getConnectionHealthHistory,
} from "~/lib/api";
import type { ConnectionInfo, ConnectionHealthStats, DBType } from "~/lib/types";
import { useConnections, useConnectionsHealth, usePlan, invalidateConnections, invalidateHealth } from "~/lib/hooks/use-gateway-data";
import { useToast } from "~/components/ui/toast";
import { useConnection } from "~/lib/connection-context";
import { DB_CONFIGS, DB_VARIANTS, DEFAULT_VARIANT, type ConnectionVariant } from "~/lib/connections/connector-catalog";
import { DEFAULT_CONNECTION_FORM as defaultForm } from "~/lib/connections/defaults";
import { buildConnectionPayload as buildCreatePayload } from "~/lib/connections/connection-payload";
import type { ConnectionForm as FormState } from "~/lib/connections/types";
import { validateConnectionForm as validateForm } from "~/lib/connections/connection-validation";
import { connectionToForm, connectionUsesAdvancedSettings } from "~/lib/connections/connection-to-form";

type SchemaSearchResponse = Awaited<ReturnType<typeof searchConnectionSchema>>;
type SchemaSearchResult = Pick<
  SchemaSearchResponse,
  "result_count" | "total_tables" | "tables"
>;

export function useConnectionsController() {
  const { toast } = useToast();
  const { refreshConnections: syncGlobalConnections } = useConnection();
  const { data: swrConnections, isLoading: connectionsLoading } = useConnections();
  const connections = swrConnections ?? [];
  const [showForm, setShowForm] = useState(false);
  const [securityBannerExpanded, setSecurityBannerExpanded] = useState(false);
  const [editingConnection, setEditingConnection] = useState<string | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<string, { status: string; message: string; phases?: { phase: string; status: string; message: string; duration_ms?: number }[]; total_duration_ms?: number }>>({});
  const [saving, setSaving] = useState(false);
  const [preTesting, setPreTesting] = useState(false);
  const [preTestResult, setPreTestResult] = useState<{ status: string; message: string; phases: { phase: string; status: string; message: string; hint?: string; duration_ms: number }[] } | null>(null);
  const [expandedConn, setExpandedConn] = useState<string | null>(null);
  const [schemaData, setSchemaData] = useState<Record<string, { tables: Record<string, { schema: string; name: string; columns: { name: string; type: string; nullable: boolean; primary_key?: boolean }[] }> }>>({});
  const [schemaLoading, setSchemaLoading] = useState<string | null>(null);
  const { data: swrHealthData } = useConnectionsHealth();
  const { data: planData } = usePlan();
  const healthData: Record<string, ConnectionHealthStats> = (() => {
    const map: Record<string, ConnectionHealthStats> = {};
    if (swrHealthData) for (const h of swrHealthData.connections) map[h.connection_name] = h;
    return map;
  })();
  const [piiData, setPiiData] = useState<Record<string, { tables_scanned: number; tables_with_pii: number; detections: Record<string, Record<string, string>> }>>({});
  const [piiLoading, setPiiLoading] = useState<string | null>(null);
  const [piiConfig, setPiiConfig] = useState<Record<string, { enabled: boolean; rules: Record<string, string> }>>({});
  const [expandedPiiConn, setExpandedPiiConn] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [schemaSearch, setSchemaSearch] = useState<Record<string, string>>({});
  const [schemaSearchResults, setSchemaSearchResults] = useState<Record<string, SchemaSearchResult>>({});
  const [schemaSearchLoading, setSchemaSearchLoading] = useState<string | null>(null);
  const [endorsements, setEndorsements] = useState<Record<string, { endorsed: string[]; hidden: string[]; mode: "all" | "endorsed_only" }>>({});
  const [form, setForm] = useState<FormState>({ ...defaultForm });
  const [selectedVariant, setSelectedVariant] = useState<string>("default");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [advancedTab, setAdvancedTab] = useState<"security" | "performance" | "schema">("security");
  const [filterTag, setFilterTag] = useState<string | null>(null);
  const [connectionSearch, setConnectionSearch] = useState("");
  const importFileRef = useRef<HTMLInputElement>(null);
  const [serverIp, setServerIp] = useState<string | null>(null);
  const [diagnosing, setDiagnosing] = useState<string | null>(null);
  const [diagResults, setDiagResults] = useState<Record<string, { host: string; port: number; diagnostics: { check: string; status: string; message: string; hint?: string; duration_ms: number }[] }>>({});
  const [schemaRefreshStatus, setSchemaRefreshStatus] = useState<Record<string, { fingerprint?: string | null; last_schema_refresh: number | null; cached: boolean; cached_table_count: number; schema_refresh_interval: number | null }>>({});
  const [schemaDiff, setSchemaDiff] = useState<Record<string, { has_changes: boolean; added_tables: string[]; removed_tables: string[]; modified_tables: unknown[] } | null>>({});
  const [exploringTable, setExploringTable] = useState<string | null>(null);
  const [exploredData, setExploredData] = useState<Record<string, { columns: { name: string; type: string; sample_values?: string[]; value_stats?: { min: unknown; max: unknown; avg: number | null } }[] }>>({});
  const [healthHistory, setHealthHistory] = useState<Record<string, number[]>>({});

  // Field ref map for scroll+focus on first invalid field
  const fieldRefs = useRef<Record<string, HTMLElement | null>>({});
  // Server-side validation errors mapped back to field keys
  const [serverFieldErrors, setServerFieldErrors] = useState<Record<string, string>>({});

  // Real-time form validation — computed on every form change.
  // errors render live because validateForm recomputes on every render; this is the existing behavior.
  const validateErrors = showForm ? validateForm(form) : {};
  const formErrors: Record<string, string> = { ...validateErrors, ...serverFieldErrors };
  const hasFormErrors = Object.keys(formErrors).length > 0;

  const refresh = useCallback(() => {
    invalidateConnections();
    invalidateHealth();
    // Sync the global connection context so other pages see updates
    syncGlobalConnections();
  }, [syncGlobalConnections]);

  // Load PII config and sparkline history whenever the connection list changes
  useEffect(() => {
    for (const conn of connections) {
      if (conn.pii_enabled || conn.pii_rules) {
        setPiiConfig((prev) => ({ ...prev, [conn.name]: { enabled: conn.pii_enabled || false, rules: conn.pii_rules || {} } }));
      }
      if (conn.db_type === "xata") continue;
      getConnectionHealthHistory(conn.name, 3600, 120).then((res) => {
        const latencies = res.buckets
          .map((b) => b.avg_latency_ms)
          .filter((v): v is number => v !== null);
        if (latencies.length >= 2) {
          setHealthHistory((prev) => ({ ...prev, [conn.name]: latencies }));
        }
      }).catch(() => {});
    }
  }, [connections]);

  // Fetch server IP for whitelist guidance
  useEffect(() => {
    getNetworkInfo().then((info) => {
      setServerIp(info.public_ip || (info.local_ips?.[0] ?? null));
    }).catch(() => {});
  }, []);

  function handleDbTypeChange(newType: DBType) {
    const config = DB_CONFIGS[newType];
    // Switching db_type invalidates connector-specific server errors (e.g. catalog for trino)
    setServerFieldErrors({});
    // Step 2 resets to the first variant of the new type; its defaults apply immediately
    const firstVariant = DB_VARIANTS[newType]?.[0] ?? DEFAULT_VARIANT;
    setSelectedVariant(firstVariant.key);
    setForm({
      ...defaultForm,
      name: form.name,
      tags: form.tags,
      tagInput: form.tagInput,
      db_type: newType,
      connectionMode: config.connectionModes[0],
      host: config.fields.includes("host") ? form.host || "localhost" : "",
      port: String(config.defaultPort || ""),
      ...firstVariant.defaults,
    } as FormState);
  }

  function handleVariantChange(variant: ConnectionVariant) {
    const config = DB_CONFIGS[form.db_type];
    setSelectedVariant(variant.key);
    setServerFieldErrors({});
    // Re-derive the form from clean defaults so options from the previous
    // variant (e.g. azure_ad_auth, iam_auth) never leak into this one.
    // Name, tags, and host survive — they are the user's own input.
    setForm({
      ...defaultForm,
      name: form.name,
      tags: form.tags,
      tagInput: form.tagInput,
      db_type: form.db_type,
      connectionMode: config.connectionModes[0],
      host: config.fields.includes("host") ? form.host || "localhost" : "",
      port: String(config.defaultPort || ""),
      ...variant.defaults,
    } as FormState);
  }

  async function handleCreate() {
    const errors = { ...validateForm(form), ...serverFieldErrors };
    const n = Object.keys(errors).length;
    if (n > 0) {
      scrollToFirstInvalidField(errors);
      toast(`Please fix ${n} field${n > 1 ? "s" : ""} before saving`, "error");
      return;
    }
    setSaving(true);
    try {
      const payload = buildCreatePayload(form);
      let saved: ConnectionInfo;
      if (editingConnection) {
        // Update existing connection
        const { name: _n, db_type: _d, ...updateFields } = payload;
        saved = await updateConnection(editingConnection, updateFields);
        toast("connection updated successfully", "success");
      } else {
        saved = await createConnection(payload);
        toast("connection created successfully", "success");
      }
      setShowForm(false);
      setEditingConnection(null);
      setForm({ ...defaultForm });
      setSelectedVariant("default");
      setServerFieldErrors({});
      setShowAdvanced(false);
      refresh();
      return saved;
    } catch (e) { handleServerError(e); } finally { setSaving(false); }
  }

  // Focus the first invalid field in this priority order.
  // In URL mode, validateForm early-returns so only name and connection_string produce errors.
  const FIELD_PRIORITY = [
    "name", "connection_string",
    "host", "port", "account", "project", "credentials_json",
    "http_path", "access_token", "dbx_oauth_client_id", "dbx_oauth_client_secret",
    "sf_private_key", "sf_oauth_token",
    "bq_oauth_token",
    "database", "catalog", "username",
    "azure_tenant_id", "azure_client_id", "azure_client_secret",
    "ssl_ca_cert",
    "ssh_host", "ssh_port", "ssh_username", "ssh_password", "ssh_private_key",
    "connection_timeout", "query_timeout",
  ] as const;

  /** Map gateway validation messages to form fields. */
  function mapServerValidationErrors(messages: string[]): { fieldErrors: Record<string, string>; unmapped: string[] } {
    const fieldErrors: Record<string, string> = {};
    const unmapped: string[] = [];
    // Evaluated in order — SSH patterns first, then specific-vendor, then generic. First match per message wins.
    const mappingTable: [string, string][] = [
      ["SSH tunnel requires a bastion host", "ssh_host"],
      ["SSH tunnel requires a username", "ssh_username"],
      ["SSH tunnel with key auth requires a private key", "ssh_private_key"],
      ["SSH tunnel with password auth requires a password", "ssh_password"],
      ["Databricks requires a server hostname", "host"],
      ["Databricks requires an HTTP path", "http_path"],
      ["Databricks requires a personal access token", "access_token"],
      ["Snowflake requires an account identifier", "account"],
      ["Snowflake requires a username", "username"],
      ["BigQuery requires a GCP project ID", "project"],
      ["BigQuery requires service account credentials JSON", "credentials_json"],
      ["Trino requires a host", "host"],
      ["Trino requires a catalog", "catalog"],
      ["requires a host", "host"],
      ["requires a username", "username"],
      ["requires a database file path", "database"],   // duckdb/sqlite — must win
      ["requires a database", "database"],              // pg/mysql/mssql/clickhouse/redshift — generic fallback
    ];
    for (const msg of messages) {
      let matched = false;
      for (const [substr, key] of mappingTable) {
        if (msg.includes(substr)) {
          fieldErrors[key] = fieldErrors[key] ?? msg;
          matched = true;
          break;
        }
      }
      if (!matched) unmapped.push(msg);
    }
    return { fieldErrors, unmapped };
  }

  /** Scroll to and focus the first invalid field, expanding collapsed sections as needed. */
  function scrollToFirstInvalidField(errors: Record<string, string>) {
    const firstKey = FIELD_PRIORITY.find((k) => errors[k]);
    if (!firstKey) return;

    const isSshField = ["ssh_host", "ssh_port", "ssh_username", "ssh_password", "ssh_private_key"].includes(firstKey);
    const isAdvancedField = ["connection_timeout", "query_timeout"].includes(firstKey);
    const isSslField = firstKey === "ssl_ca_cert";
    const isAzureAdField = ["azure_tenant_id", "azure_client_id", "azure_client_secret"].includes(firstKey);

    const focusEl = () => {
      requestAnimationFrame(() => {
        const el = fieldRefs.current[firstKey];
        el?.scrollIntoView({ behavior: "smooth", block: "center" });
        requestAnimationFrame(() => {
          fieldRefs.current[firstKey]?.focus({ preventScroll: true });
        });
      });
    };

    if (isSslField) {
      if (!showAdvanced) setShowAdvanced(true);
      setAdvancedTab("security");
    } else if (isSshField) {
      if (!showAdvanced) setShowAdvanced(true);
      setAdvancedTab("security");
      if (!form.ssh_enabled) setForm((prev) => ({ ...prev, ssh_enabled: true }));
    } else if (isAdvancedField) {
      if (!showAdvanced) setShowAdvanced(true);
      setAdvancedTab("performance");
    } else if (isAzureAdField) {
      if (!form.azure_ad_auth) setForm((prev) => ({ ...prev, azure_ad_auth: true }));
    }

    // Double-rAF is safe whether or not we just expanded a section
    focusEl();
  }

  function _parseError(e: unknown): string {
    const msg = String(e);
    // Parse validation errors from the API
    try {
      const match = msg.match(/\{.*"validation_errors".*\}/);
      if (match) {
        const parsed = JSON.parse(match[0]) as { validation_errors?: string[] };
        if (parsed.validation_errors) {
          return parsed.validation_errors.join("; ");
        }
      }
    } catch {}
    // Clean up generic error messages
    return msg.replace(/^Error:\s*\d+:\s*/, "").replace(/^"?(.*?)"?$/, "$1").slice(0, 200);
  }

  /** Attempt to parse gateway validation_errors from an error, map to fields, scroll to first. Falls back to _parseError toast. */
  function handleServerError(e: unknown) {
    const msg = String(e);
    // Strip "Error: <status>: " prefix to get raw body
    const body = msg.replace(/^Error:\s*\d+:\s*/, "");
    try {
      const parsed: unknown = JSON.parse(body);
      if (parsed && typeof parsed === "object") {
        const obj = parsed as Record<string, unknown>;
        const validationArr =
          (obj.detail && typeof obj.detail === "object" && (obj.detail as Record<string, unknown>).validation_errors) ||
          obj.validation_errors;
        if (Array.isArray(validationArr) && validationArr.every((v) => typeof v === "string")) {
          const { fieldErrors, unmapped } = mapServerValidationErrors(validationArr as string[]);
          if (Object.keys(fieldErrors).length > 0) {
            setServerFieldErrors((prev) => ({ ...prev, ...fieldErrors }));
            const mergedErrors = { ...formErrors, ...fieldErrors };
            scrollToFirstInvalidField(mergedErrors);
          }
          if (unmapped.length > 0) {
            toast(unmapped.join("; "), "error");
          } else if (Object.keys(fieldErrors).length === 0) {
            // validation_errors was empty/unparseable — avoid silent failure
            toast(_parseError(e), "error");
          }
          return;
        }
      }
    } catch {
      // JSON parse failed — fall through to _parseError
    }
    toast(_parseError(e), "error");
  }

  async function handleSaveAndTest() {
    const errors = { ...validateForm(form), ...serverFieldErrors };
    const n = Object.keys(errors).length;
    if (n > 0) {
      scrollToFirstInvalidField(errors);
      toast(`Please fix ${n} field${n > 1 ? "s" : ""} before saving`, "error");
      return;
    }
    setSaving(true);
    try {
      const payload = buildCreatePayload(form);
      if (editingConnection) {
        const { name: _n, db_type: _d, ...updateFields } = payload;
        await updateConnection(editingConnection, updateFields);
      } else {
        await createConnection(payload);
      }
      setShowForm(false);
      setEditingConnection(null);
      setForm({ ...defaultForm });
      setSelectedVariant("default");
      setServerFieldErrors({});
      setShowAdvanced(false);
      refresh();
      // Test the saved connection before reporting success.
      const connName = editingConnection || (payload.name as string);
      toast(`${connName}: testing connection...`, "info");
      const result = await testConnection(connName);
      setTestResult((prev) => ({ ...prev, [connName]: result }));
      toast(result.status === "healthy" ? `${connName}: connection healthy` : `${connName}: ${result.message}`, result.status === "healthy" ? "success" : "error");
    } catch (e) { handleServerError(e); } finally { setSaving(false); }
  }

  async function handlePreTest() {
    const errors = { ...validateForm(form), ...serverFieldErrors };
    const n = Object.keys(errors).length;
    if (n > 0) {
      scrollToFirstInvalidField(errors);
      toast(`Please fix ${n} field${n > 1 ? "s" : ""} before saving`, "error");
      return;
    }
    setPreTesting(true);
    setPreTestResult(null);
    try {
      const payload = buildCreatePayload(form);
      const result = await testCredentials(payload);
      setPreTestResult(result);
      if (result.status === "healthy") {
        toast("connection test passed — ready to save", "success");
      } else {
        const failedPhase = result.phases?.find((p: { status: string }) => p.status === "error");
        toast(failedPhase?.message || result.message, "error");
      }
      return result;
    } catch (e) {
      handleServerError(e);
      setPreTestResult({ status: "error", message: _parseError(e), phases: [] });
      return null;
    } finally {
      setPreTesting(false);
    }
  }

  function handleEditConnection(connection: ConnectionInfo) {
    setForm(connectionToForm(connection));
    setEditingConnection(connection.name);
    setShowForm(true);
    setServerFieldErrors({});
    setShowAdvanced(connectionUsesAdvancedSettings(connection));
  }


  async function handleTest(name: string) {
    setTesting(name);
    setDiagResults((prev) => { const next = { ...prev }; delete next[name]; return next; });
    try {
      const result = await testConnection(name);
      setTestResult((prev) => ({ ...prev, [name]: result }));
      toast(result.status === "healthy" ? `${name}: connection healthy` : `${name}: ${result.message}`, result.status === "healthy" ? "success" : "error");
    } catch (e) {
      setTestResult((prev) => ({ ...prev, [name]: { status: "error", message: String(e) } }));
      toast(`${name}: test failed`, "error");
    } finally { setTesting(null); }
  }

  async function handleGenerateSemantic(name: string) {
    try {
      const result = await generateSemanticModel(name);
      toast(`${name}: semantic model generated — ${result.joins} joins, ${result.glossary_terms} glossary terms`, "success");
    } catch (e) {
      toast(`${name}: semantic model generation failed — ${String(e)}`, "error");
    }
  }

  async function handleDiagnose(name: string) {
    setDiagnosing(name);
    setTestResult((prev) => { const next = { ...prev }; delete next[name]; return next; });
    try {
      const result = await diagnoseConnection(name);
      setDiagResults((prev) => ({ ...prev, [name]: result }));
      const allOk = result.diagnostics.every((d: { status: string }) => d.status === "ok");
      toast(allOk ? `${name}: all checks passed` : `${name}: see diagnostic results`, allOk ? "success" : "info");
    } catch (e) {
      toast(`${name}: diagnose failed — ${String(e)}`, "error");
    } finally { setDiagnosing(null); }
  }

  async function handleDelete(name: string) { setDeleteTarget(name); }

  async function confirmDelete() {
    if (!deleteTarget) return;
    await deleteConnection(deleteTarget);
    refresh();
    toast(`${deleteTarget} deleted`, "info");
    setDeleteTarget(null);
  }

  async function handleClone(name: string) {
    const newName = prompt(`Clone "${name}" as:`, `${name}-copy`);
    if (!newName || !newName.trim()) return;
    try {
      await cloneConnection(name, newName.trim());
      refresh();
      toast(`Cloned as "${newName.trim()}"`, "success");
    } catch (error) {
      const message = error instanceof Error ? error.message : "unknown error";
      toast(`Clone failed: ${message.slice(0, 80)}`, "error");
    }
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
    // Load endorsements if not cached
    if (!endorsements[name]) {
      try {
        const e = await getSchemaEndorsements(name);
        setEndorsements(prev => ({ ...prev, [name]: e }));
      } catch {}
    }
    // Load schema refresh status (fingerprint, last refresh time)
    getSchemaRefreshStatus(name)
      .then((status) => setSchemaRefreshStatus(prev => ({ ...prev, [name]: status })))
      .catch(() => {});
    // Load schema diff if available
    getConnectionSchemaDiff(name)
      .then((diff) => {
        const schemaChanges = diff.diff;
        if (schemaChanges) {
          setSchemaDiff(prev => ({ ...prev, [name]: schemaChanges }));
        }
      })
      .catch(() => {});
  }

  async function reloadConnectionSchema(name: string) {
    const data = await getConnectionSchema(name);
    setSchemaData((prev) => ({ ...prev, [name]: { tables: data.tables } }));
  }

  async function handleRefreshSchema(name: string) {
    setSchemaLoading(name);
    try {
      await refreshConnectionSchema(name);
      await reloadConnectionSchema(name);
      const [status, diff] = await Promise.all([
        getSchemaRefreshStatus(name).catch(() => null),
        getConnectionSchemaDiff(name).catch(() => null),
      ]);
      if (status) setSchemaRefreshStatus((prev) => ({ ...prev, [name]: status }));
      setSchemaDiff((prev) => ({ ...prev, [name]: diff?.diff ?? null }));
      toast(`${name}: schema refreshed`, "success");
    } catch {
      toast(`${name}: refresh failed`, "error");
    } finally {
      setSchemaLoading(null);
    }
  }

  async function handleExploreTable(name: string, tableKey: string) {
    const exploreKey = `${name}:${tableKey}`;
    if (exploredData[exploreKey]) {
      setExploredData((prev) => { const next = { ...prev }; delete next[exploreKey]; return next; });
      return;
    }
    setExploringTable(exploreKey);
    try {
      const data = await exploreColumns(name, tableKey);
      setExploredData((prev) => ({ ...prev, [exploreKey]: data }));
    } catch {
      toast("Column exploration failed", "error");
    } finally {
      setExploringTable(null);
    }
  }

  async function handleScanPII(name: string) {
    setPiiLoading(name);
    try {
      const data = await detectAndSavePII(name);
      // Update PII display data
      const detections: Record<string, Record<string, string>> = {};
      for (const [col, rule] of Object.entries(data.rules)) {
        const table = "_all";
        if (!detections[table]) detections[table] = {};
        detections[table][col] = rule;
      }
      setPiiData((prev) => ({ ...prev, [name]: { tables_scanned: 0, tables_with_pii: Object.keys(detections).length, detections } }));
      setPiiConfig((prev) => ({ ...prev, [name]: { enabled: data.enabled, rules: data.rules } }));
      toast(`${name}: ${data.columns_flagged} PII columns detected and redaction enabled`, "success");
    } catch {
      // Fallback to detect-only
      try {
        const data = await detectPII(name);
        setPiiData((prev) => ({ ...prev, [name]: data }));
      } catch { setPiiData((prev) => ({ ...prev, [name]: { tables_scanned: 0, tables_with_pii: 0, detections: {} } })); }
    }
    finally { setPiiLoading(null); }
  }

  async function handleTogglePII(name: string) {
    const current = piiConfig[name];
    if (!current) {
      // No config yet — run detection first
      await handleScanPII(name);
      return;
    }
    const newEnabled = !current.enabled;
    try {
      const result = await setPIIConfig(name, { enabled: newEnabled, rules: current.rules });
      setPiiConfig((prev) => ({ ...prev, [name]: result }));
      toast(`${name}: PII redaction ${newEnabled ? "enabled" : "disabled"}`, newEnabled ? "success" : "info");
    } catch (e) {
      toast(`Failed to toggle PII: ${e instanceof Error ? e.message : "unknown error"}`, "error");
    }
  }

  const searchTimerRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  function handleSchemaSearch(name: string, query: string) {
    setSchemaSearch((prev) => ({ ...prev, [name]: query }));
    // Clear previous debounce timer
    if (searchTimerRef.current[name]) {
      clearTimeout(searchTimerRef.current[name]);
    }
    if (!query.trim()) {
      setSchemaSearchResults((prev) => { const n = { ...prev }; delete n[name]; return n; });
      return;
    }
    // Debounce 300ms to avoid excessive API calls
    searchTimerRef.current[name] = setTimeout(async () => {
      setSchemaSearchLoading(name);
      try {
        const data = await searchConnectionSchema(name, query);
        setSchemaSearchResults((prev) => ({ ...prev, [name]: { result_count: data.result_count, total_tables: data.total_tables, tables: data.tables } }));
      } catch {
        setSchemaSearchResults((prev) => ({ ...prev, [name]: { result_count: 0, total_tables: 0, tables: {} } }));
      } finally {
        setSchemaSearchLoading(null);
      }
    }, 300);
  }

  async function handleExport() {
    try {
      const data = await exportConnections(false);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `signalpilot-connections-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error("Export failed:", err);
    }
  }

  async function handleImportFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const manifest = JSON.parse(text) as Record<string, unknown>;
      const result = await importConnections(manifest);
      refresh();
      const msg = [`Imported: ${result.imported}`];
      if (result.skipped.length) msg.push(`Skipped (existing): ${result.skipped.join(", ")}`);
      if (result.errors.length) msg.push(`Errors: ${result.errors.map(e => `${e.name}: ${e.error}`).join("; ")}`);
      alert(msg.join("\n"));
    } catch (err) {
      alert(`Import failed: ${err instanceof Error ? err.message : err}`);
    }
    // Reset file input
    if (importFileRef.current) importFileRef.current.value = "";
  }

  const config = DB_CONFIGS[form.db_type];

  return {
    toast,
    connectionsLoading,
    connections,
    showForm,
    setShowForm,
    securityBannerExpanded,
    setSecurityBannerExpanded,
    editingConnection,
    setEditingConnection,
    testing,
    testResult,
    saving,
    preTesting,
    preTestResult,
    setPreTestResult,
    expandedConn,
    setExpandedConn,
    schemaData,
    schemaLoading,
    healthData,
    planData,
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
    form,
    setForm,
    selectedVariant,
    showAdvanced,
    setShowAdvanced,
    advancedTab,
    setAdvancedTab,
    filterTag,
    setFilterTag,
    connectionSearch,
    setConnectionSearch,
    importFileRef,
    serverIp,
    diagnosing,
    diagResults,
    schemaRefreshStatus,
    schemaDiff,
    exploringTable,
    exploredData,
    healthHistory,
    fieldRefs,
    serverFieldErrors,
    setServerFieldErrors,
    formErrors,
    hasFormErrors,
    handleDbTypeChange,
    handleVariantChange,
    handleCreate,
    handleSaveAndTest,
    handlePreTest,
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
    handleExport,
    handleImportFile,
    config,
  };
}

export type ConnectionsController = ReturnType<typeof useConnectionsController>;
