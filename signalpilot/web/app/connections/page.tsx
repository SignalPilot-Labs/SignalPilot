"use client";

import { useEffect, useState, useCallback, useRef, type MutableRefObject } from "react";
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
  Link2,
  Settings2,
  Lock,
  Server,
  Pencil,
  RefreshCw,
  Search,
  Copy,
  EyeOff,
  Star,
  Filter,
  Download,
  Upload,
  Folder,
  FileText,
  ArrowLeft,
  HardDrive,
} from "lucide-react";
import {
  createConnection,
  updateConnection,
  deleteConnection,
  cloneConnection,
  testConnection,
  getConnectionSchema,
  searchConnectionSchema,
  detectPII,
  getPIIConfig,
  setPIIConfig,
  detectAndSavePII,
  refreshConnectionSchema,
  getSchemaEndorsements,
  setSchemaEndorsements,
  exportConnections,
  importConnections,
  getNetworkInfo,
  diagnoseConnection,
  generateSemanticModel,
  testCredentials,
  getSchemaRefreshStatus,
  getConnectionSchemaDiff,
  exploreColumns,
  getConnectionHealthHistory,
  browseFiles,
} from "~/lib/api";
import type { ConnectionInfo, ConnectionHealthStats, DBType, SSHTunnelConfig, SSLConfig } from "~/lib/types";
import { useConnections, useConnectionsHealth, usePlan, invalidateConnections, invalidateHealth } from "~/lib/hooks/use-gateway-data";
import { PageLoader } from "~/components/ui/page-loader";
import { EmptyDatabase, EmptyState } from "~/components/ui/empty-states";
import { CONNECTIONS_TABS, PageHeader } from "~/components/ui/page-header";
import { StatusDot, MiniBar, Sparkline } from "~/components/ui/data-viz";
import { Tooltip } from "~/components/ui/tooltip";
import { useToast } from "~/components/ui/toast";
import { ConfirmDialog } from "~/components/ui/confirm-dialog";
import { useConnection } from "~/lib/connection-context";
import { ConnectionSchemaBrowser, type ConnectionSchemaTable } from "./connection-schema-browser";
import { DbTypeIcon } from "~/components/connections/db-type-icon";
import { LocalDbFilePicker } from "~/components/connections/editor/local-db-file-picker";
import { FormInput, FormTextArea, fieldProps } from "~/components/connections/editor/form-controls";
import { ConnectionFieldsForm } from "~/components/connections/editor/connection-fields-form";
import { SslSection as SSLSection, SshSection as SSHSection } from "~/components/connections/editor/security-sections";
import {
  CATEGORY_LABELS,
  CONNECTOR_TIERS,
  DB_CONFIGS,
  DB_TYPE_LABELS as dbTypeLabels,
  DB_TYPE_ORDER,
  DB_VARIANTS,
  DEFAULT_VARIANT,
  type ConnectionVariant,
} from "~/lib/connections/connector-catalog";
import { DEFAULT_CONNECTION_FORM as defaultForm } from "~/lib/connections/defaults";
import { buildConnectionPayload as buildCreatePayload } from "~/lib/connections/connection-payload";
import type { ConnectionForm as FormState } from "~/lib/connections/types";
import { buildConnectionPreview, detectDbTypeFromUrl, parseConnectionUrl } from "~/lib/connections/connection-url";
import { validateConnectionForm as validateForm } from "~/lib/connections/connection-validation";
import "./connections.css";
const IS_CLOUD_MODE = process.env.NEXT_PUBLIC_DEPLOYMENT_MODE === "cloud";
/* ── Local DB File Picker (DuckDB / SQLite) ── */
/* ── Database type SVG icons ── */
/* ── Form field components ── */
/* ── DB-specific form sections ── */
export default function ConnectionsPage() {
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
  const [schemaSearchResults, setSchemaSearchResults] = useState<Record<string, { result_count: number; total_tables: number; tables: Record<string, any> }>>({});
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
      if ((conn as any).pii_enabled || (conn as any).pii_rules) {
        setPiiConfig((prev) => ({ ...prev, [conn.name]: { enabled: (conn as any).pii_enabled || false, rules: (conn as any).pii_rules || {} } }));
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
      if (editingConnection) {
        // Update existing connection
        const { name: _n, db_type: _d, ...updateFields } = payload;
        await updateConnection(editingConnection, updateFields);
        toast("connection updated successfully", "success");
      } else {
        await createConnection(payload);
        toast("connection created successfully", "success");
      }
      setShowForm(false);
      setEditingConnection(null);
      setForm({ ...defaultForm });
      setSelectedVariant("default");
      setServerFieldErrors({});
      setShowAdvanced(false);
      refresh();
    } catch (e) { handleServerError(e); } finally { setSaving(false); }
  }

  // §6 priority order for scroll/focus — first hit wins.
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

  /** Map gateway validation_errors[] strings to field keys (§7). */
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
      // Auto-test after save
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
    } catch (e) {
      handleServerError(e);
      setPreTestResult({ status: "error", message: _parseError(e), phases: [] });
    } finally {
      setPreTesting(false);
    }
  }

  function handleEditConnection(conn: ConnectionInfo) {
    const connConfig = DB_CONFIGS[conn.db_type as DBType] || DB_CONFIGS.postgres;
    setForm({
      ...defaultForm,
      name: conn.name,
      db_type: conn.db_type as DBType,
      connectionMode: connConfig.connectionModes[0],
      host: conn.host || "",
      port: String(conn.port || connConfig.defaultPort || ""),
      database: conn.database || "",
      username: conn.username || "",
      password: "", // Never pre-fill passwords
      description: conn.description || "",
      account: conn.account || "",
      warehouse: conn.warehouse || "",
      schema_name: conn.schema_name || "",
      role: conn.role || "",
      // Snowflake auth method — derived from the gateway `authenticator` value.
      snowflake_auth_method: (() => {
        const a = String((conn as any).authenticator || "").toLowerCase();
        if (a.includes("okta.com")) return "okta";
        if (a === "key_pair" || a === "snowflake_jwt") return "key_pair";
        if (a === "oauth") return "oauth";
        if (a === "pat") return "pat";
        if (a === "mfa" || a === "username_password_mfa") return "mfa";
        return "password";
      })(),
      sf_okta_url: String((conn as any).authenticator || "").includes("okta.com") ? String((conn as any).authenticator) : "",
      snowflake_host: (conn as any).snowflake_host || "",
      snowflake_protocol: (conn as any).snowflake_protocol === "http" ? "http" : "https",
      project: conn.project || "",
      dataset: conn.dataset || "",
      bq_location: (conn as any).location || "",
      bq_max_bytes_billed: (conn as any).maximum_bytes_billed ? String((conn as any).maximum_bytes_billed) : "",
      http_path: conn.http_path || "",
      catalog: conn.catalog || "",
      // Xata (secrets are never pre-filled)
      branch: (conn as any).branch || (conn.db_type === "xata" ? "main" : ""),
      xata_api_key: "",
      xata_organization: (conn as any).xata_organization || "",
      xata_project: (conn as any).xata_project || "",
      xata_database: (conn as any).xata_database || (conn.db_type === "xata" ? "xata" : ""),
      xata_api_url: (conn as any).xata_api_url || (conn.db_type === "xata" ? "https://api.xata.tech" : ""),
      ssl_enabled: conn.ssl || false,
      ssl_mode: conn.ssl_config?.mode || "require",
      ssl_ca_cert: conn.ssl_config?.ca_cert || "",
      ssl_client_cert: conn.ssl_config?.client_cert || "",
      ssl_client_key: conn.ssl_config?.client_key || "",
      ssh_enabled: conn.ssh_tunnel?.enabled || false,
      ssh_host: conn.ssh_tunnel?.host || "",
      ssh_port: String(conn.ssh_tunnel?.port || 22),
      ssh_username: conn.ssh_tunnel?.username || "",
      ssh_auth_method: conn.ssh_tunnel?.auth_method || "password",
      ssh_proxy_enabled: !!(conn.ssh_tunnel as any)?.proxy_host,
      ssh_proxy_host: (conn.ssh_tunnel as any)?.proxy_host || "",
      ssh_proxy_port: String((conn.ssh_tunnel as any)?.proxy_port || 3128),
      tags: conn.tags || [],
      schema_refresh_enabled: !!(conn.schema_refresh_interval),
      schema_refresh_interval: String(conn.schema_refresh_interval || 300),
      scope: (conn as any).scope || "workspace",
      read_only: (conn as any).read_only !== false,
      schema_filter_include: (conn.schema_filter_include || []).join(", "),
      schema_filter_exclude: (conn.schema_filter_exclude || []).join(", "),
      connection_timeout: String(conn.connection_timeout || 15),
      query_timeout: String(conn.query_timeout || 120),
      keepalive_interval: String(conn.keepalive_interval || 0),
      // Pool size (PostgreSQL)
      pool_min_size: String((conn as any).pool_min_size || 1),
      pool_max_size: String((conn as any).pool_max_size || 5),
      // IAM auth
      iam_auth: (conn as any).auth_method === "iam",
      aws_region: (conn as any).aws_region || "us-east-1",
      aws_access_key_id: "", // Never pre-fill secrets
      aws_secret_access_key: "",
      redshift_cluster_id: (conn as any).cluster_id || "",
      redshift_workgroup: (conn as any).workgroup || "",
      // Azure AD auth
      azure_ad_auth: (conn as any).auth_method === "azure_ad",
      azure_tenant_id: (conn as any).azure_tenant_id || "",
      azure_client_id: (conn as any).azure_client_id || "",
      azure_client_secret: "", // Never pre-fill secrets
    });
    setEditingConnection(conn.name);
    setShowForm(true);
    setServerFieldErrors({}); // clear stale server errors when loading a connection (§8)
    const hasCustomTimeouts = (conn.connection_timeout && conn.connection_timeout !== 15) || (conn.query_timeout && conn.query_timeout !== 120) || (conn.keepalive_interval && conn.keepalive_interval > 0);
    setShowAdvanced(!!(conn.ssl || conn.ssh_tunnel?.enabled || conn.schema_refresh_interval || conn.schema_filter_include?.length || conn.schema_filter_exclude?.length || hasCustomTimeouts));
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
    } catch (err: any) {
      toast(`Clone failed: ${err.message?.slice(0, 80) || "unknown error"}`, "error");
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
        if (diff.diff) setSchemaDiff(prev => ({ ...prev, [name]: diff.diff as any }));
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
      setSchemaDiff((prev) => ({ ...prev, [name]: diff?.diff ? diff.diff as any : null }));
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

  async function handleImportFile(e: React.ChangeEvent<HTMLInputElement>) {
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

  if (connectionsLoading) return <PageLoader label="loading connections" />;

  return (
    <div className="connections-page animate-fade-in">
      <input
        ref={importFileRef}
        type="file"
        accept=".json"
        className="hidden"
        onChange={handleImportFile}
      />
      <PageHeader
        title="Connections"
        subtitle="Data access"
        tabs={CONNECTIONS_TABS}
        description="Manage governed warehouse access, health, schema visibility, and credential controls."
        actions={
          <div className="flex items-center gap-2">
            <a
              href="/query"
              className="flex items-center gap-1.5 px-3 py-2 border border-[var(--color-border)] rounded-[10px] text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:border-[var(--color-border-hover)] transition-colors duration-150"
              title="Open the governed SQL query console"
            >
              query console
            </a>
            <button
              onClick={handleExport}
              className="flex items-center gap-1.5 px-3 py-2 border border-[var(--color-border)] rounded-[10px] text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:border-[var(--color-border-hover)] transition-colors duration-150"
              title="Export connections"
            >
              <Download className="w-3 h-3" /> Export
            </button>
            <button
              onClick={() => importFileRef.current?.click()}
              className="flex items-center gap-1.5 px-3 py-2 border border-[var(--color-border)] rounded-[10px] text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:border-[var(--color-border-hover)] transition-colors duration-150"
              title="Import connections from JSON"
            >
              <Upload className="w-3 h-3" /> Import
            </button>
            <button
              onClick={() => setShowForm(true)}
              className="flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium rounded-[10px] transition-opacity duration-150 hover:opacity-90"
            >
              <Plus className="w-3.5 h-3.5" /> Add connection
            </button>
          </div>
        }
      />

      <section className="connections-overview" aria-label="Connection overview">
        <div><span>Connections</span><strong>{connections.length}/{planData?.limits.connections === "unlimited" ? "unlimited" : (planData?.limits.connections ?? "--")}</strong><small>{planData?.tier ?? "local"} plan</small></div>
        <div><span>Healthy</span><strong>{connections.filter((connection) => healthData[connection.name]?.status === "healthy").length}</strong><small>{connections.filter((connection) => !healthData[connection.name] || healthData[connection.name]?.status === "unknown").length} awaiting samples</small></div>
        <div><span>Needs attention</span><strong>{connections.filter((connection) => ["warning", "degraded", "unhealthy"].includes(healthData[connection.name]?.status ?? "")).length}</strong><small>Health and connectivity</small></div>
        <div><span>PII protection</span><strong>{Object.values(piiConfig).filter((config) => config.enabled).length}</strong><small>Active connections</small></div>
        <div className="connections-security">
          <Shield aria-hidden="true" />
          <div><strong>Credential custody active</strong><small>Encrypted storage, scoped access, audited use</small></div>
          <button type="button" onClick={() => setSecurityBannerExpanded(!securityBannerExpanded)} aria-expanded={securityBannerExpanded} aria-label="Show credential security details">{securityBannerExpanded ? <ChevronDown /> : <ChevronRight />}</button>
        </div>
        {securityBannerExpanded && <div className="connections-security-details"><span>Encrypted before persistence</span><span>PBKDF2 key derivation</span><span>Secrets decrypted in memory only</span><span>Connection access is audited</span><span>Passwords are never returned</span></div>}
      </section>

      {/* ─── Create Connection Form ─── */}
      {showForm && (
        <div className="connection-form-shell animate-scale-in">
          <header>
            <div className="flex items-center gap-2">
              <DbTypeIcon type={form.db_type} />
              <span className="text-[11px] text-[var(--color-text-dim)] uppercase tracking-[0.08em]">
                {editingConnection ? `edit ${editingConnection}` : `new ${DB_CONFIGS[form.db_type].label} connection`}
              </span>
            </div>
            <span className="text-[11px] text-[var(--color-text-dim)] opacity-50">
              {DB_CONFIGS[form.db_type].description}
            </span>
          </header>

          <div className="connection-form-body">
            {/* Step 1: database type */}
            <div className="mb-5">
              <label className="block text-[12px] text-[var(--color-text-dim)] mb-2">
                {editingConnection ? "database type" : <><span className="font-medium text-[var(--color-text)]">1.</span> select a database</>}
              </label>
              <div className="flex flex-wrap gap-1.5">
                {DB_TYPE_ORDER.filter((t) => !IS_CLOUD_MODE || t !== "sqlite").map((dbType) => {
                  const cfg = DB_CONFIGS[dbType];
                  const isSelected = form.db_type === dbType;
                  return (
                    <button
                      key={dbType}
                      onClick={() => handleDbTypeChange(dbType)}
                      className={`flex items-center gap-1.5 px-3 py-1.5 text-[12px] border rounded-[6px] transition-colors duration-150 ${
                        isSelected
                          ? "border-[var(--color-text)] text-[var(--color-text)] bg-[var(--color-text)]/5"
                          : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)]"
                      }`}
                    >
                      <DbTypeIcon type={dbType} />
                      {cfg.label}
                      <span className={`text-[10px] opacity-60 ${CONNECTOR_TIERS[dbType]?.tier === 1 ? "text-emerald-400" : CONNECTOR_TIERS[dbType]?.tier === 2 ? "text-sky-400" : "text-zinc-400"}`}>
                        {CONNECTOR_TIERS[dbType]?.label}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Step 2: variant of the selected database type — only for new connections */}
            {!editingConnection && (() => {
              const variants = DB_VARIANTS[form.db_type] ?? [DEFAULT_VARIANT];
              const active = variants.find((v) => v.key === selectedVariant) ?? variants[0];
              return (
                <div className="mb-5">
                  <label className="block text-[12px] text-[var(--color-text-dim)] mb-2">
                    <span className="font-medium text-[var(--color-text)]">2.</span> where is your {DB_CONFIGS[form.db_type].label} running?
                  </label>
                  <div className="flex flex-wrap gap-1.5">
                    {variants.map((variant) => {
                      const isSelected = variant.key === active.key;
                      return (
                        <button
                          key={variant.key}
                          type="button"
                          onClick={() => handleVariantChange(variant)}
                          className={`flex items-center gap-1.5 px-3 py-1.5 text-[12px] border rounded-[6px] transition-colors duration-150 ${
                            isSelected
                              ? "border-[var(--color-text)] text-[var(--color-text)] bg-[var(--color-text)]/5"
                              : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)]"
                          }`}
                        >
                          {variant.label}
                        </button>
                      );
                    })}
                  </div>
                  <p className="text-[11px] text-[var(--color-text-dim)] mt-1.5 opacity-70">{active.hint}</p>
                </div>
              );
            })()}

            {/* Name + Description */}
            <div className="grid grid-cols-2 gap-4 mb-4">
              {editingConnection ? (
                <div>
                  <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5">connection name</label>
                  <div className="px-3 py-2 bg-[var(--color-bg-hover)] border border-[var(--color-border)] rounded-[10px] text-xs text-[var(--color-text-dim)] font-mono">{editingConnection}</div>
                </div>
              ) : (
                <FormInput label="connection name" value={form.name} onChange={(v) => { setForm({ ...form, name: v }); setServerFieldErrors((prev) => { if (!("name" in prev)) return prev; const { name: _, ...rest } = prev; return rest; }); }} placeholder="prod-analytics" hint="alphanumeric, dashes, underscores" required {...fieldProps("name", formErrors, fieldRefs)} />
              )}
              <FormInput label="description" value={form.description} onChange={(v) => setForm({ ...form, description: v })} placeholder="Production analytics DB" />
            </div>

            {/* Tags */}
            <div className="mb-4">
              <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5">tags</label>
              <div className="flex flex-wrap items-center gap-1.5">
                {form.tags.map((tag) => (
                  <span key={tag} className="flex items-center gap-1 px-2 py-0.5 text-[11px] bg-[var(--color-bg-hover)] border border-[var(--color-border)] rounded-[6px] text-[var(--color-text-dim)]">
                    {tag}
                    <button type="button" onClick={() => setForm({ ...form, tags: form.tags.filter(t => t !== tag) })} className="text-[var(--color-text-dim)] hover:text-[var(--color-error)] ml-0.5">&times;</button>
                  </span>
                ))}
                <input
                  type="text"
                  value={form.tagInput}
                  onChange={(e) => setForm({ ...form, tagInput: e.target.value })}
                  onKeyDown={(e) => {
                    if ((e.key === "Enter" || e.key === ",") && form.tagInput.trim()) {
                      e.preventDefault();
                      const tag = form.tagInput.trim().toLowerCase().replace(/[^a-z0-9_-]/g, "");
                      if (tag && !form.tags.includes(tag)) {
                        setForm({ ...form, tags: [...form.tags, tag], tagInput: "" });
                      } else {
                        setForm({ ...form, tagInput: "" });
                      }
                    }
                  }}
                  placeholder={form.tags.length === 0 ? "prod, analytics, team-data..." : "add tag..."}
                  className="flex-1 min-w-[100px] px-2 py-1 text-[12px] bg-transparent border-none outline-none text-[var(--color-text)] placeholder:text-[var(--color-text-dim)]"
                />
              </div>
              <p className="text-[11px] text-[var(--color-text-dim)] mt-1 opacity-60">press enter or comma to add — organize connections by environment, team, or purpose</p>
            </div>

            {/* Connection mode toggle (fields vs URL) — bidirectional sync */}
            {config.connectionModes.length > 1 && (
              <div className="flex items-center gap-3 mb-4">
                <span className="text-[12px] text-[var(--color-text-dim)]">connect via:</span>
                {config.connectionModes.map((mode) => (
                  <button
                    key={mode}
                    onClick={() => {
                      if (mode === form.connectionMode) return;
                      if (mode === "url") {
                        // Fields → URL: build connection string from current fields
                        const preview = buildConnectionPreview({ ...form, connectionMode: "fields" });
                        setForm({ ...form, connectionMode: "url", connection_string: preview.replace(":****@", `:${form.password || ""}@`) });
                      } else {
                        // URL → Fields: parse connection string into fields
                        const parsed = parseConnectionUrl(form.connection_string, form.db_type);
                        setForm({ ...form, connectionMode: "fields", ...parsed });
                      }
                    }}
                    className={`flex items-center gap-1.5 px-2.5 py-1 text-[12px] border rounded-[6px] transition-colors duration-150 ${
                      form.connectionMode === mode
                        ? "border-[var(--color-text)] text-[var(--color-text)]"
                        : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:border-[var(--color-border-hover)]"
                    }`}
                  >
                    {mode === "url" ? <Link2 className="w-3 h-3" strokeWidth={1.5} /> : <Settings2 className="w-3 h-3" strokeWidth={1.5} />}
                    {mode === "url" ? "connection string" : "individual fields"}
                  </button>
                ))}
              </div>
            )}

            {/* DB-specific fields */}
            <div className="grid grid-cols-2 gap-4 mb-4">
              <ConnectionFieldsForm form={form} setForm={setForm} formErrors={formErrors} fieldRefs={fieldRefs} clearServerError={(key) => setServerFieldErrors((prev) => { if (!(key in prev)) return prev; const { [key]: _, ...rest } = prev; return rest; })} />
            </div>

            {/* Connection string preview with copy button */}
            {form.connectionMode !== "url" && (
              <div className="mb-4 px-3 py-2 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed rounded-[10px]">
                <div className="flex items-center gap-2">
                  <Link2 className="w-3 h-3 text-[var(--color-text-dim)]" strokeWidth={1.5} />
                  <span className="text-[11px] text-[var(--color-text-dim)]">connection preview</span>
                  <div className="flex-1" />
                  <button
                    type="button"
                    onClick={() => {
                      const fullUrl = buildConnectionPreview({ ...form, connectionMode: "fields" }).replace(":****@", `:${form.password || ""}@`);
                      navigator.clipboard.writeText(fullUrl).then(() => toast("Connection URL copied", "info"));
                    }}
                    className="text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"
                  >
                    copy url
                  </button>
                </div>
                <code className="text-[12px] text-[var(--color-text-muted)] font-mono break-all">{buildConnectionPreview(form)}</code>
              </div>
            )}

            {/* Advanced: SSL + SSH + Access Controls + Schema Refresh */}
            <div>
              <button
                type="button"
                onClick={() => setShowAdvanced(!showAdvanced)}
                className="flex items-center gap-1.5 text-[12px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors mb-2"
              >
                {showAdvanced ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                advanced options
                {(form.ssl_enabled || form.ssh_enabled || !form.read_only || form.schema_refresh_enabled || form.connection_timeout !== "15" || form.query_timeout !== "120") && (
                  <span className="text-[var(--color-success)] text-[11px] ml-1">
                    {[form.ssl_enabled && "ssl", form.ssh_enabled && "ssh", !form.read_only && "read-write", form.schema_refresh_enabled && "auto-refresh", (form.connection_timeout !== "15" || form.query_timeout !== "120") && "custom timeouts"].filter(Boolean).join(" + ")}
                  </span>
                )}
              </button>
                {showAdvanced && (
                  <div className="animate-fade-in">
                    {/* HEX-style sub-tabs: Security | Performance | Schema */}
                    <div className="flex gap-0 mb-4 border-b border-[var(--color-border)]">
                      {(["security", "performance", "schema"] as const).map((tab) => {
                        const tabIcons = { security: <Lock className="w-3 h-3" strokeWidth={1.5} />, performance: <Activity className="w-3 h-3" strokeWidth={1.5} />, schema: <Table2 className="w-3 h-3" strokeWidth={1.5} /> };
                        const tabBadges = {
                          security: form.ssl_enabled || form.ssh_enabled,
                          performance: form.connection_timeout !== "15" || form.query_timeout !== "120" || form.keepalive_interval !== "0",
                          schema: form.schema_refresh_enabled || form.schema_filter_include.trim() !== "" || form.schema_filter_exclude.trim() !== "",
                        };
                        return (
                          <button
                            key={tab}
                            type="button"
                            onClick={() => setAdvancedTab(tab)}
                            className={`flex items-center gap-1.5 px-3 py-2 text-[12px] border-b-2 transition-colors duration-150 ${
                              advancedTab === tab
                                ? "border-[var(--color-text)] text-[var(--color-text)]"
                                : "border-transparent text-[var(--color-text-dim)] hover:text-[var(--color-text-muted)]"
                            }`}
                          >
                            {tabIcons[tab]}
                            {tab}
                            {tabBadges[tab] && <span className="w-1.5 h-1.5 bg-emerald-400 rounded-full" />}
                          </button>
                        );
                      })}
                    </div>

                    {/* Security tab */}
                    {advancedTab === "security" && (
                      <div className="animate-fade-in">
                    <SSLSection form={form} setForm={setForm} formErrors={formErrors} fieldRefs={fieldRefs} />
                    <SSHSection form={form} setForm={setForm} serverIp={serverIp} formErrors={formErrors} fieldRefs={fieldRefs} clearServerError={(key) => setServerFieldErrors((prev) => { if (!(key in prev)) return prev; const { [key]: _, ...rest } = prev; return rest; })} />
                    {/* Connection Scope + Read-only (HEX pattern) */}
                    <div className="border-t border-[var(--color-border)] pt-4 mt-4">
                      <div className="flex items-center gap-2 text-[12px] text-[var(--color-text-dim)] mb-3">
                        <Settings2 className="w-3 h-3" strokeWidth={1.5} />
                        <span>access controls</span>
                      </div>
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5">connection scope</label>
                          <select
                            value={form.scope}
                            onChange={(e) => setForm({ ...form, scope: e.target.value as "workspace" | "project" })}
                            className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] rounded-[10px] text-xs focus:outline-none focus:border-[var(--color-text-dim)]"
                          >
                            <option value="workspace">workspace — all projects</option>
                            <option value="project">project — current only</option>
                          </select>
                          <p className="text-[10px] text-[var(--color-text-dim)] mt-1 opacity-60">
                            workspace connections are shared across all projects
                          </p>
                        </div>
                        <div>
                          <label className="flex items-center gap-2 cursor-pointer mt-5">
                            <input
                              type="checkbox"
                              checked={form.read_only}
                              onChange={(e) => setForm({ ...form, read_only: e.target.checked })}
                              className="accent-[var(--color-text)]"
                            />
                            <span className="text-[12px] text-[var(--color-text-muted)]">
                              read-only mode
                            </span>
                          </label>
                          <p className="text-[10px] text-[var(--color-text-dim)] mt-1 opacity-60 ml-5">
                            only SELECT queries allowed (recommended)
                          </p>
                        </div>
                      </div>
                    </div>

                    {/* IP Allowlist Info */}
                    <div className="border-t border-[var(--color-border)] pt-4 mt-4">
                      <div className="flex items-center gap-2 text-[12px] text-[var(--color-text-dim)] mb-2">
                        <Shield className="w-3 h-3" strokeWidth={1.5} />
                        <span>ip allowlisting</span>
                      </div>
                      <div className="px-3 py-2.5 bg-[var(--color-bg)]/50 border border-[var(--color-border)] border-dashed rounded-[10px]">
                        <p className="text-[11px] text-[var(--color-text-dim)] mb-1.5">
                          if your database requires ip allowlisting, add this signalpilot server ip to your firewall rules:
                        </p>
                        <div className="flex flex-wrap gap-2">
                          <code className="text-[12px] text-[var(--color-text)] bg-[var(--color-bg-hover)] px-2 py-0.5 font-mono">
                            {serverIp ? `${serverIp}/32` : "detecting..."}
                          </code>
                          {serverIp && (
                            <button
                              type="button"
                              onClick={() => { navigator.clipboard.writeText(serverIp); toast("IP copied to clipboard", "success"); }}
                              className="text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors"
                            >
                              <Copy className="w-3 h-3 inline" /> copy
                            </button>
                          )}
                        </div>
                        <p className="text-[10px] text-[var(--color-text-dim)] mt-1.5 opacity-60">
                          {serverIp ? "add this ip to your database firewall, security group, or network policy." : "fetching server ip..."}
                        </p>
                      </div>
                    </div>
                      </div>
                    )}

                    {/* Performance tab */}
                    {advancedTab === "performance" && (
                      <div className="animate-fade-in">
                        {/* Connection Timeouts */}
                        <div>
                          <div className="flex items-center gap-2 text-[12px] text-[var(--color-text-dim)] mb-3">
                            <Clock className="w-3 h-3" strokeWidth={1.5} />
                            <span>timeouts & keepalive</span>
                          </div>
                          <div className="grid grid-cols-3 gap-4">
                            <div>
                              {(() => { const { id: ctId, inputRef: ctRef, error: ctError } = fieldProps("connection_timeout", formErrors, fieldRefs); return (
                              <>
                              <label htmlFor={ctId} className="block text-[12px] text-[var(--color-text-dim)] mb-1.5">connection timeout</label>
                              <div className="flex items-center gap-1.5">
                                <input type="number" min="1" max="300" id={ctId} ref={ctRef as React.Ref<HTMLInputElement>} aria-invalid={ctError ? "true" : undefined} aria-describedby={ctError ? `${ctId}-error` : undefined} value={form.connection_timeout} onChange={(e) => setForm({ ...form, connection_timeout: e.target.value })} className={`w-20 px-3 py-2 bg-[var(--color-bg-input)] border rounded-[10px] text-xs focus:outline-none font-mono tabular-nums${ctError ? " border-[var(--color-error)]/60 focus:border-[var(--color-error)]" : " border-[var(--color-border)] focus:border-[var(--color-text-dim)]"}`} />
                                <span className="text-[11px] text-[var(--color-text-dim)]">sec</span>
                              </div>
                              {ctError && <p id={`${ctId}-error`} role="alert" className="text-[11px] text-[var(--color-error)] mt-1">{ctError}</p>}
                              <p className="text-[10px] text-[var(--color-text-dim)] mt-1 opacity-60">max time to establish connection</p>
                              </>
                              ); })()}
                            </div>
                            <div>
                              {(() => { const { id: qtId, inputRef: qtRef, error: qtError } = fieldProps("query_timeout", formErrors, fieldRefs); return (
                              <>
                              <label htmlFor={qtId} className="block text-[12px] text-[var(--color-text-dim)] mb-1.5">query timeout</label>
                              <div className="flex items-center gap-1.5">
                                <input type="number" min="1" max="3600" id={qtId} ref={qtRef as React.Ref<HTMLInputElement>} aria-invalid={qtError ? "true" : undefined} aria-describedby={qtError ? `${qtId}-error` : undefined} value={form.query_timeout} onChange={(e) => setForm({ ...form, query_timeout: e.target.value })} className={`w-20 px-3 py-2 bg-[var(--color-bg-input)] border rounded-[10px] text-xs focus:outline-none font-mono tabular-nums${qtError ? " border-[var(--color-error)]/60 focus:border-[var(--color-error)]" : " border-[var(--color-border)] focus:border-[var(--color-text-dim)]"}`} />
                                <span className="text-[11px] text-[var(--color-text-dim)]">sec</span>
                              </div>
                              {qtError && <p id={`${qtId}-error`} role="alert" className="text-[11px] text-[var(--color-error)] mt-1">{qtError}</p>}
                              <p className="text-[10px] text-[var(--color-text-dim)] mt-1 opacity-60">max query execution time</p>
                              </>
                              ); })()}
                            </div>
                            <div>
                              <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5">keepalive interval</label>
                              <div className="flex items-center gap-1.5">
                                <select value={form.keepalive_interval} onChange={(e) => setForm({ ...form, keepalive_interval: e.target.value })} className="bg-[var(--color-bg)] border border-[var(--color-border)] rounded-[10px] text-[var(--color-text)] text-[12px] px-2 py-2">
                                  <option value="0">disabled</option>
                                  <option value="30">30 sec</option>
                                  <option value="60">1 min</option>
                                  <option value="120">2 min</option>
                                  <option value="300">5 min</option>
                                </select>
                              </div>
                              <p className="text-[10px] text-[var(--color-text-dim)] mt-1 opacity-60">ping to prevent idle disconnect</p>
                            </div>
                          </div>
                          {/* Pool sizing — only for pool-capable connectors */}
                          {(form.db_type === "postgres") && (
                            <div className="grid grid-cols-2 gap-4 mt-3 pt-3 border-t border-[var(--color-border)]/50">
                              <div>
                                <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5">pool min size</label>
                                <div className="flex items-center gap-1.5">
                                  <input type="number" min="1" max="20" value={form.pool_min_size} onChange={(e) => setForm({ ...form, pool_min_size: e.target.value })} className="w-20 px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] rounded-[10px] text-xs focus:outline-none focus:border-[var(--color-text-dim)] font-mono tabular-nums" />
                                  <span className="text-[11px] text-[var(--color-text-dim)]">conns</span>
                                </div>
                                <p className="text-[10px] text-[var(--color-text-dim)] mt-1 opacity-60">minimum idle connections</p>
                              </div>
                              <div>
                                <label className="block text-[12px] text-[var(--color-text-dim)] mb-1.5">pool max size</label>
                                <div className="flex items-center gap-1.5">
                                  <input type="number" min="1" max="50" value={form.pool_max_size} onChange={(e) => setForm({ ...form, pool_max_size: e.target.value })} className="w-20 px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] rounded-[10px] text-xs focus:outline-none focus:border-[var(--color-text-dim)] font-mono tabular-nums" />
                                  <span className="text-[11px] text-[var(--color-text-dim)]">conns</span>
                                </div>
                                <p className="text-[10px] text-[var(--color-text-dim)] mt-1 opacity-60">max concurrent connections</p>
                              </div>
                            </div>
                          )}
                        </div>
                      </div>
                    )}

                    {/* Schema tab */}
                    {advancedTab === "schema" && (
                      <div className="animate-fade-in">
                        {/* Schema Filtering */}
                        <div>
                          <div className="flex items-center gap-2 text-[12px] text-[var(--color-text-dim)] mb-2">
                            <Filter className="w-3 h-3" strokeWidth={1.5} />
                            <span>schema filtering</span>
                          </div>
                          <div className="text-[10px] text-[var(--color-text-dim)] mb-3 opacity-60">
                            filter which schemas are visible to the ai agent. excludes staging, dev, and raw schemas to improve accuracy.
                          </div>
                          <div className="space-y-3">
                            <div>
                              <label className="block text-[11px] text-[var(--color-text-muted)] mb-1">
                                include schemas <span className="opacity-50">(comma-separated, empty = all)</span>
                              </label>
                              <input type="text" placeholder="public, analytics, production" value={form.schema_filter_include} onChange={(e) => setForm({ ...form, schema_filter_include: e.target.value })} className="w-full bg-[var(--color-bg)] border border-[var(--color-border)] rounded-[10px] text-[var(--color-text)] text-[12px] px-3 py-2 placeholder:text-[var(--color-text-dim)]" />
                            </div>
                            <div>
                              <label className="block text-[11px] text-[var(--color-text-muted)] mb-1">
                                exclude schemas <span className="opacity-50">(comma-separated, glob patterns supported)</span>
                              </label>
                              <input type="text" placeholder="staging*, dev*, raw, tmp*, _dbt_*" value={form.schema_filter_exclude} onChange={(e) => setForm({ ...form, schema_filter_exclude: e.target.value })} className="w-full bg-[var(--color-bg)] border border-[var(--color-border)] rounded-[10px] text-[var(--color-text)] text-[12px] px-3 py-2 placeholder:text-[var(--color-text-dim)]" />
                            </div>
                          </div>
                        </div>

                        {/* Scheduled Schema Refresh */}
                        <div className="border-t border-[var(--color-border)] pt-4 mt-4">
                          <div className="flex items-center gap-2 text-[12px] text-[var(--color-text-dim)] mb-2">
                            <RefreshCw className="w-3 h-3" strokeWidth={1.5} />
                            <span>scheduled schema refresh</span>
                          </div>
                          <div className="flex items-center gap-3 mb-2">
                            <label className="flex items-center gap-2 cursor-pointer">
                              <input type="checkbox" checked={form.schema_refresh_enabled} onChange={(e) => setForm({ ...form, schema_refresh_enabled: e.target.checked })} className="accent-[var(--color-text)]" />
                              <span className="text-[12px] text-[var(--color-text-muted)]">auto-refresh schema metadata</span>
                            </label>
                          </div>
                          {form.schema_refresh_enabled && (
                            <div className="flex items-center gap-2 animate-fade-in">
                              <span className="text-[11px] text-[var(--color-text-dim)]">every</span>
                              <select value={form.schema_refresh_interval} onChange={(e) => setForm({ ...form, schema_refresh_interval: e.target.value })} className="bg-[var(--color-bg)] border border-[var(--color-border)] rounded-[10px] text-[var(--color-text)] text-[12px] px-2 py-1">
                                <option value="60">1 min</option>
                                <option value="300">5 min</option>
                                <option value="900">15 min</option>
                                <option value="1800">30 min</option>
                                <option value="3600">1 hour</option>
                                <option value="14400">4 hours</option>
                                <option value="43200">12 hours</option>
                                <option value="86400">24 hours</option>
                              </select>
                              <span className="text-[10px] text-[var(--color-text-dim)] opacity-60">keeps ai agent schema knowledge current</span>
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>

            {/* Pre-test result display */}
            {preTestResult && (
              <div className={`mt-4 p-3 border rounded-[10px] ${preTestResult.status === "healthy" ? "border-emerald-500/30 bg-emerald-500/5" : "border-red-500/30 bg-red-500/5"}`}>
                <div className="flex items-center gap-2 mb-2">
                  {preTestResult.status === "healthy" ? (
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                  ) : (
                    <XCircle className="w-3.5 h-3.5 text-red-400" />
                  )}
                  <span className={`text-[12px] font-medium ${preTestResult.status === "healthy" ? "text-emerald-400" : "text-red-400"}`}>
                    {preTestResult.message}
                  </span>
                </div>
                {preTestResult.phases?.length > 0 && (
                  <div className="space-y-1 ml-5">
                    {preTestResult.phases.map((phase, i) => (
                      <div key={i} className="flex items-center gap-2 text-[11px]">
                        <span className={phase.status === "ok" ? "text-emerald-400" : phase.status === "error" ? "text-red-400" : "text-amber-400"}>
                          {phase.status === "ok" ? "pass" : phase.status === "error" ? "fail" : phase.status}
                        </span>
                        <span className="text-[var(--color-text-dim)]">{phase.phase}:</span>
                        <span className="text-[var(--color-text-muted)]">{phase.message}</span>
                        {phase.duration_ms !== undefined && (
                          <span className="text-[var(--color-text-dim)] opacity-50">{phase.duration_ms.toFixed(0)}ms</span>
                        )}
                      </div>
                    ))}
                    {preTestResult.phases.some(p => p.hint) && (
                      <div className="mt-1.5 pl-2 border-l border-amber-500/30">
                        {preTestResult.phases.filter(p => p.hint).map((p, i) => (
                          <div key={i} className="text-[11px] text-amber-400/80">
                            hint: {p.hint}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Connection warnings (HEX pattern — proactive security guidance) */}
            {(() => {
              const warnings: string[] = [];
              const cfg = DB_CONFIGS[form.db_type];
              // Warn if SSL not enabled on a production-capable connector.
              // In URL mode, check the connection string for sslmode= param.
              const urlHasSsl = form.connectionMode === "url" && form.connection_string &&
                /[?&]sslmode=(require|verify-ca|verify-full|prefer|allow)/i.test(form.connection_string);
              if (cfg.supportsSSL && !form.ssl_enabled && !urlHasSsl && !["duckdb", "sqlite"].includes(form.db_type)) {
                warnings.push("SSL/TLS is not enabled. Recommended for production databases to encrypt traffic in transit.");
              }
              // Warn if using password auth for Snowflake (key-pair is preferred per HEX)
              if (form.db_type === "snowflake" && form.snowflake_auth_method === "password") {
                warnings.push("Snowflake recommends key-pair authentication over password. Password auth may be blocked by Snowflake's mandatory MFA policy.");
              }
              // Warn about read-write mode
              if (!form.read_only) {
                warnings.push("Read-write mode enabled. This allows INSERT, UPDATE, DELETE, and DDL queries. Use read-only for analytics workloads.");
              }
              // Warn about missing schema filtering for large warehouses
              if (["snowflake", "bigquery", "redshift", "databricks"].includes(form.db_type) && !form.schema_filter_include.trim() && !form.schema_filter_exclude.trim()) {
                warnings.push("No schema filtering configured. For large warehouses, filtering schemas improves AI agent accuracy and reduces metadata overhead.");
              }
              if (warnings.length === 0) return null;
              return (
                <div className="mt-4 space-y-1.5">
                  {warnings.map((w, i) => (
                    <div key={i} className="flex items-start gap-2 px-3 py-2 border border-amber-500/20 bg-amber-500/5 rounded-[10px]">
                      <AlertTriangle className="w-3 h-3 text-amber-400 flex-shrink-0 mt-0.5" strokeWidth={1.5} />
                      <span className="text-[11px] text-amber-400/80">{w}</span>
                    </div>
                  ))}
                </div>
              );
            })()}

            {/* Action buttons */}
            <div className="flex items-center gap-3 mt-5 pt-4 border-t border-[var(--color-border)]">
              <button onClick={handleCreate} disabled={saving || preTesting || hasFormErrors} className="flex items-center gap-2 px-4 py-2 bg-[var(--color-text)] text-[var(--color-bg)] text-xs font-medium rounded-[10px] transition-opacity duration-150 hover:opacity-90 disabled:opacity-30">
                {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                {editingConnection ? "update connection" : "save connection"}
              </button>
              <button onClick={handlePreTest} disabled={saving || preTesting || hasFormErrors} className="flex items-center gap-2 px-4 py-2 border border-emerald-500/30 rounded-[10px] text-xs text-emerald-400 hover:bg-emerald-500/10 hover:border-emerald-500/50 transition-colors duration-150 disabled:opacity-40 disabled:cursor-not-allowed">
                {preTesting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <TestTube className="w-3.5 h-3.5" strokeWidth={1.5} />}
                test connection
              </button>
              <button onClick={handleSaveAndTest} disabled={saving || preTesting || hasFormErrors} className="flex items-center gap-2 px-4 py-2 border border-[var(--color-border)] rounded-[10px] text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:border-[var(--color-border-hover)] transition-colors duration-150 disabled:opacity-40 disabled:cursor-not-allowed">
                {editingConnection ? "update & test" : "save & test"}
              </button>
              <button onClick={() => { setShowForm(false); setEditingConnection(null); setForm({ ...defaultForm }); setServerFieldErrors({}); setShowAdvanced(false); setPreTestResult(null); }} className="px-4 py-2 text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors">
                cancel
              </button>
              {editingConnection && (
                <span className="text-[11px] text-[var(--color-text-dim)] opacity-60 ml-auto">
                  leave password blank to keep existing credentials
                </span>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ─── Connections List ─── */}
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
        <div className="connection-list">
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

            // Build display string — prefer connection_string for URL-mode connections
            let displayStr = "";
            if ((conn as any).connection_string && !conn.host) {
              try {
                const u = new URL((conn as any).connection_string.replace(/^(postgresql|postgres|redshift|clickhouse|mysql\+pymysql|mssql|mssql\+pymssql|sqlserver|trino(\+https)?|snowflake|databricks):/, "http:"));
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
                      {(conn as any).byok_key_alias && (
                        <Tooltip content={`Credentials encrypted with your key: ${(conn as any).byok_key_alias}`} position="top">
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
    </div>
  );
}
