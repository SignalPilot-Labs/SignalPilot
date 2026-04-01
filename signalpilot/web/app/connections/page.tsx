"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Plus,
  Database,
  Trash2,
  CheckCircle2,
  XCircle,
  Loader2,
  TestTube,
  ArrowLeft,
  ArrowRight,
  Shield,
  Lock,
  Table2,
  Zap,
  Clock,
  Server,
  Eye,
  EyeOff,
  ChevronDown,
  ChevronUp,
  AlertCircle,
  Info,
  X,
  HardDrive,
  Layers,
  RefreshCw,
} from "lucide-react";
import {
  getConnections,
  createConnection,
  deleteConnection,
  testConnection,
} from "@/lib/api";
import type { ConnectionInfo } from "@/lib/types";

/* ─── Database Type Definitions ──────────────────────────────────────── */

const DB_TYPES = [
  {
    type: "postgres",
    name: "PostgreSQL",
    description: "Advanced open source relational database",
    defaultPort: "5432",
    color: "#336791",
    gradient: "from-[#336791] to-[#2a5478]",
    lightColor: "rgba(51, 103, 145, 0.12)",
    borderColor: "rgba(51, 103, 145, 0.3)",
    status: "available" as const,
    icon: (
      <svg viewBox="0 0 32 32" className="w-8 h-8" fill="none">
        <path
          d="M22.839 26.4c-.596.254-1.133.37-1.554.37-.734 0-1.092-.412-1.092-1.264v-.069c.01-.445.089-1.03.243-1.68.15-.63.22-1.13.22-1.48 0-1.06-.47-1.64-1.72-2.12l-.36-.14c.99-.63 1.72-1.27 2.2-1.94.69-.96 1.04-2.11 1.04-3.43 0-1.45-.33-2.6-.98-3.42-.34-.43-.82-.85-1.43-1.26.1-.7.25-1.47.45-2.31.2-.85.3-1.5.3-1.95 0-1.17-.43-2.1-1.28-2.8C17.97 2.31 16.85 2 15.54 2c-1.11 0-2.09.24-2.95.73-.85.48-1.56 1.18-2.12 2.1-.01.02-.02.04-.02.06l-.53 1.26c-.52-.07-1.03-.1-1.55-.1-1.89 0-3.38.51-4.49 1.53C2.63 8.7 2 10.15 2 12.02c0 2.22.67 4.58 2 7.08 1.36 2.57 2.87 4.53 4.52 5.87.93.76 1.79 1.13 2.55 1.13.65 0 1.31-.29 2-.88l.12-.12.36.08c.67.15 1.34.22 2 .22.89 0 1.71-.12 2.46-.37l.36-.12.12.1c.64.53 1.29.79 1.95.79.79 0 1.65-.4 2.59-1.2.95-.81 1.77-1.87 2.47-3.18.26-.48.47-.95.64-1.39-.51.2-1.18.4-1.76.57l-.49.15zm-6.1-4.15c.82.3 1.3.54 1.44.73.13.18.2.54.2 1.06 0 .22-.06.57-.19 1.05a9.6 9.6 0 00-.27 1.89c0 .15.01.29.02.42-.37.12-.83.18-1.38.18a6.5 6.5 0 01-1.61-.21l-1.18-.34-.76.72c-.43.41-.82.62-1.16.62-.44 0-1.05-.3-1.81-.9-1.45-1.15-2.79-2.94-4.02-5.37C4.74 18.87 4.15 16.73 4.15 12.02c0-1.36.44-2.46 1.31-3.27.87-.82 2.02-1.23 3.43-1.23.64 0 1.31.06 2 .2l.95.19.54-1.3c.02-.05.04-.1.06-.16.4-.68.89-1.2 1.46-1.55.58-.36 1.23-.54 1.95-.54.86 0 1.56.2 2.09.6.52.39.78.93.78 1.6 0 .31-.09.84-.27 1.58a17.2 17.2 0 00-.44 2.32l-.07.54.48.28c.68.39 1.18.77 1.5 1.14.45.51.67 1.25.67 2.22 0 1.03-.27 1.91-.8 2.65-.52.72-1.32 1.36-2.39 1.92l-1.36.7 1.38.53z"
          fill="currentColor"
          className="text-[#336791]"
        />
      </svg>
    ),
  },
  {
    type: "mysql",
    name: "MySQL",
    description: "Popular database for web applications",
    defaultPort: "3306",
    color: "#00758f",
    gradient: "from-[#00758f] to-[#005f73]",
    lightColor: "rgba(0, 117, 143, 0.12)",
    borderColor: "rgba(0, 117, 143, 0.3)",
    status: "available" as const,
    icon: (
      <svg viewBox="0 0 32 32" className="w-8 h-8" fill="none">
        <path
          d="M7.5 7C5 7 3 8.3 3 11v10c0 2.7 2 4 4.5 4h17c2.5 0 4.5-1.3 4.5-4V11c0-2.7-2-4-4.5-4h-17zm1.2 3.2h2.1v7.3H9.1v-5.7l-2.4 5.7H5.4l-2.4-5.7v5.7H1.3v-7.3h2.3l2.05 5.1 2.05-5.1zm6.3 0h2v4.1l3.4-4.1h2.4L19 14.8l4 2.7h-2.8l-3-2.05-1.2 1.37v.68h-1.5v-7.3zm11 0h5.7v1.4h-3.7v1.3h3.4v1.4h-3.4v1.7h3.9v1.5H26v-7.3z"
          fill="currentColor"
          className="text-[#00758f]"
        />
      </svg>
    ),
  },
  {
    type: "duckdb",
    name: "DuckDB",
    description: "Fast analytical database — no server needed",
    defaultPort: "",
    color: "#FFC107",
    gradient: "from-[#FFC107] to-[#FF9800]",
    lightColor: "rgba(255, 193, 7, 0.12)",
    borderColor: "rgba(255, 193, 7, 0.3)",
    status: "coming_soon" as const,
    icon: (
      <svg viewBox="0 0 32 32" className="w-8 h-8" fill="none">
        <circle cx="16" cy="16" r="12" fill="currentColor" className="text-[#FFC107]" opacity="0.15" />
        <text
          x="16"
          y="21"
          textAnchor="middle"
          fontSize="14"
          fill="currentColor"
          className="text-[#FFC107]"
          fontWeight="bold"
        >
          D
        </text>
      </svg>
    ),
  },
  {
    type: "snowflake",
    name: "Snowflake",
    description: "Cloud-native enterprise data warehouse",
    defaultPort: "443",
    color: "#29B5E8",
    gradient: "from-[#29B5E8] to-[#1DA1D0]",
    lightColor: "rgba(41, 181, 232, 0.12)",
    borderColor: "rgba(41, 181, 232, 0.3)",
    status: "coming_soon" as const,
    icon: (
      <svg viewBox="0 0 32 32" className="w-8 h-8" fill="none">
        <path
          d="M16 4v24M4 16h24M7.5 7.5l17 17M24.5 7.5l-17 17M16 4l3 3-3 3-3-3 3-3zM16 22l3 3-3 3-3-3 3-3zM4 16l3-3 3 3-3 3-3-3zM22 16l3-3 3 3-3 3-3-3z"
          stroke="currentColor"
          className="text-[#29B5E8]"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
      </svg>
    ),
  },
];

/* ─── Wizard Steps ───────────────────────────────────────────────────── */

type WizardStep = "list" | "select_type" | "configure" | "testing" | "success";

interface TestResult {
  status: string;
  healthy?: boolean;
  message?: string;
  latency_ms?: number;
  server_version?: string;
  database_name?: string;
  table_count?: number;
  schema_preview?: Array<{
    schema: string;
    table: string;
    columns: number;
    size: string;
  }>;
  ssl_active?: boolean;
  max_connections?: number;
  current_connections?: number;
  server_uptime?: string;
  error_hint?: string;
  error_code?: string;
}

/* ─── Main Component ─────────────────────────────────────────────────── */

export default function ConnectionsPage() {
  const [connections, setConnections] = useState<ConnectionInfo[]>([]);
  const [step, setStep] = useState<WizardStep>("list");
  const [testing, setTesting] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({});
  const [saving, setSaving] = useState(false);
  const [expandedCard, setExpandedCard] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [form, setForm] = useState({
    name: "",
    db_type: "postgres",
    host: "",
    port: "5432",
    database: "",
    username: "",
    password: "",
    description: "",
    ssl: false,
  });
  const [wizardTestResult, setWizardTestResult] = useState<TestResult | null>(null);

  const refresh = useCallback(() => {
    getConnections().then(setConnections).catch(() => {});
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const selectedDbType = DB_TYPES.find((d) => d.type === form.db_type);

  function resetForm() {
    setForm({
      name: "",
      db_type: "postgres",
      host: "",
      port: "5432",
      database: "",
      username: "",
      password: "",
      description: "",
      ssl: false,
    });
    setStep("list");
    setWizardTestResult(null);
    setShowPassword(false);
  }

  function selectDbType(type: string) {
    const dbType = DB_TYPES.find((d) => d.type === type);
    if (!dbType || dbType.status === "coming_soon") return;
    setForm({
      ...form,
      db_type: type,
      port: dbType.defaultPort,
    });
    setStep("configure");
  }

  async function handleTestAndSave() {
    setStep("testing");
    setWizardTestResult(null);
    setSaving(true);

    try {
      // First create the connection
      await createConnection({
        name: form.name,
        db_type: form.db_type,
        host: form.host || undefined,
        port: parseInt(form.port) || undefined,
        database: form.database || undefined,
        username: form.username || undefined,
        password: form.password || undefined,
        description: form.description,
        ssl: form.ssl,
      });

      // Then test it
      const result = await testConnection(form.name);
      setWizardTestResult(result);

      if (result.status === "healthy") {
        setStep("success");
      } else {
        // Connection was created but test failed — keep it but show the error
        setStep("testing");
      }
      refresh();
    } catch (e) {
      setWizardTestResult({
        status: "error",
        message: String(e),
        error_hint: "Failed to create the connection. Check if a connection with this name already exists.",
      });
    } finally {
      setSaving(false);
    }
  }

  async function handleTestExisting(name: string) {
    setTesting(name);
    try {
      const result = await testConnection(name);
      setTestResults((prev) => ({ ...prev, [name]: result }));
    } catch (e) {
      setTestResults((prev) => ({
        ...prev,
        [name]: { status: "error", message: String(e) },
      }));
    } finally {
      setTesting(null);
    }
  }

  async function handleDelete(name: string) {
    await deleteConnection(name);
    setDeleteConfirm(null);
    refresh();
  }

  const isFormValid =
    form.name.trim().length > 0 &&
    form.name.length <= 64 &&
    form.host.trim().length > 0 &&
    form.database.trim().length > 0 &&
    form.username.trim().length > 0;

  /* ─── Wizard: Select Database Type ──────────────────────────────────── */

  if (step === "select_type") {
    return (
      <div className="p-8 max-w-4xl mx-auto">
        <button
          onClick={resetForm}
          className="flex items-center gap-2 text-sm text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors mb-8"
        >
          <ArrowLeft className="w-4 h-4" /> Back to connections
        </button>

        <div className="text-center mb-10">
          <h1 className="text-2xl font-semibold mb-2">Add a data connection</h1>
          <p className="text-sm text-[var(--color-text-muted)]">
            Choose your database type to get started
          </p>
        </div>

        <div className="grid grid-cols-2 gap-4">
          {DB_TYPES.map((db) => {
            const isAvailable = db.status === "available";
            return (
              <button
                key={db.type}
                onClick={() => selectDbType(db.type)}
                disabled={!isAvailable}
                className={`group relative flex items-start gap-4 p-5 rounded-xl border text-left transition-all duration-200 ${
                  isAvailable
                    ? "border-[var(--color-border)] hover:border-[color:var(--hover-border)] hover:bg-[color:var(--hover-bg)] cursor-pointer hover:shadow-lg hover:shadow-[color:var(--hover-shadow)] hover:-translate-y-0.5"
                    : "border-[var(--color-border)] opacity-50 cursor-not-allowed"
                }`}
                style={
                  {
                    "--hover-border": db.borderColor,
                    "--hover-bg": db.lightColor,
                    "--hover-shadow": `${db.color}10`,
                  } as React.CSSProperties
                }
              >
                <div
                  className="flex-shrink-0 w-12 h-12 rounded-xl flex items-center justify-center"
                  style={{ backgroundColor: db.lightColor }}
                >
                  {db.icon}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-medium text-sm">{db.name}</span>
                    {!isAvailable && (
                      <span className="text-[10px] px-2 py-0.5 rounded-full bg-[var(--color-bg-hover)] text-[var(--color-text-dim)] font-medium uppercase tracking-wider">
                        Coming Soon
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-[var(--color-text-muted)] leading-relaxed">
                    {db.description}
                  </p>
                </div>
                {isAvailable && (
                  <ArrowRight className="w-4 h-4 text-[var(--color-text-dim)] group-hover:text-[var(--color-text-muted)] transition-colors flex-shrink-0 mt-1" />
                )}
              </button>
            );
          })}
        </div>
      </div>
    );
  }

  /* ─── Wizard: Configure Connection ──────────────────────────────────── */

  if (step === "configure" && selectedDbType) {
    return (
      <div className="p-8 max-w-2xl mx-auto">
        <button
          onClick={() => setStep("select_type")}
          className="flex items-center gap-2 text-sm text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors mb-8"
        >
          <ArrowLeft className="w-4 h-4" /> Back to database selection
        </button>

        {/* Header with DB type badge */}
        <div className="flex items-center gap-4 mb-8">
          <div
            className="w-12 h-12 rounded-xl flex items-center justify-center"
            style={{ backgroundColor: selectedDbType.lightColor }}
          >
            {selectedDbType.icon}
          </div>
          <div>
            <h1 className="text-xl font-semibold">
              Connect to {selectedDbType.name}
            </h1>
            <p className="text-xs text-[var(--color-text-muted)] mt-0.5">
              Enter your database credentials below
            </p>
          </div>
        </div>

        {/* Form */}
        <div className="space-y-5">
          {/* Connection name */}
          <div>
            <label className="block text-xs font-medium text-[var(--color-text-muted)] mb-1.5">
              Connection name
            </label>
            <input
              type="text"
              placeholder="e.g. prod-analytics, staging-warehouse"
              value={form.name}
              onChange={(e) =>
                setForm({
                  ...form,
                  name: e.target.value
                    .toLowerCase()
                    .replace(/[^a-z0-9-_]/g, "-")
                    .slice(0, 64),
                })
              }
              className="w-full px-3 py-2.5 rounded-lg bg-[var(--color-bg-input)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent)] focus:ring-1 focus:ring-[var(--color-accent)]/30 transition-all"
            />
            <p className="text-[11px] text-[var(--color-text-dim)] mt-1">
              A unique identifier for this connection. Lowercase letters, numbers, and hyphens only.
            </p>
          </div>

          {/* Host & Port row */}
          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-2">
              <label className="block text-xs font-medium text-[var(--color-text-muted)] mb-1.5">
                Host
              </label>
              <input
                type="text"
                placeholder={selectedDbType.type === "postgres" ? "localhost or db.example.com" : "localhost"}
                value={form.host}
                onChange={(e) => setForm({ ...form, host: e.target.value })}
                className="w-full px-3 py-2.5 rounded-lg bg-[var(--color-bg-input)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent)] focus:ring-1 focus:ring-[var(--color-accent)]/30 transition-all"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-[var(--color-text-muted)] mb-1.5">
                Port
              </label>
              <input
                type="text"
                placeholder={selectedDbType.defaultPort}
                value={form.port}
                onChange={(e) => setForm({ ...form, port: e.target.value })}
                className="w-full px-3 py-2.5 rounded-lg bg-[var(--color-bg-input)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent)] focus:ring-1 focus:ring-[var(--color-accent)]/30 transition-all"
              />
            </div>
          </div>

          {/* Database */}
          <div>
            <label className="block text-xs font-medium text-[var(--color-text-muted)] mb-1.5">
              Database
            </label>
            <input
              type="text"
              placeholder="my_database"
              value={form.database}
              onChange={(e) => setForm({ ...form, database: e.target.value })}
              className="w-full px-3 py-2.5 rounded-lg bg-[var(--color-bg-input)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent)] focus:ring-1 focus:ring-[var(--color-accent)]/30 transition-all"
            />
          </div>

          {/* Divider */}
          <div className="border-t border-[var(--color-border)] pt-5">
            <div className="flex items-center gap-2 mb-4">
              <Lock className="w-3.5 h-3.5 text-[var(--color-text-dim)]" />
              <span className="text-xs font-medium text-[var(--color-text-muted)]">
                Authentication
              </span>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-[var(--color-text-muted)] mb-1.5">
                  Username
                </label>
                <input
                  type="text"
                  placeholder="postgres"
                  value={form.username}
                  onChange={(e) =>
                    setForm({ ...form, username: e.target.value })
                  }
                  className="w-full px-3 py-2.5 rounded-lg bg-[var(--color-bg-input)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent)] focus:ring-1 focus:ring-[var(--color-accent)]/30 transition-all"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-[var(--color-text-muted)] mb-1.5">
                  Password
                </label>
                <div className="relative">
                  <input
                    type={showPassword ? "text" : "password"}
                    value={form.password}
                    onChange={(e) =>
                      setForm({ ...form, password: e.target.value })
                    }
                    className="w-full px-3 py-2.5 pr-10 rounded-lg bg-[var(--color-bg-input)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent)] focus:ring-1 focus:ring-[var(--color-accent)]/30 transition-all"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[var(--color-text-dim)] hover:text-[var(--color-text-muted)] transition-colors"
                  >
                    {showPassword ? (
                      <EyeOff className="w-4 h-4" />
                    ) : (
                      <Eye className="w-4 h-4" />
                    )}
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* SSL Toggle */}
          <div className="flex items-center justify-between p-3 rounded-lg bg-[var(--color-bg-input)] border border-[var(--color-border)]">
            <div className="flex items-center gap-3">
              <Shield className="w-4 h-4 text-[var(--color-text-dim)]" />
              <div>
                <span className="text-sm font-medium">SSL / TLS</span>
                <p className="text-[11px] text-[var(--color-text-dim)] mt-0.5">
                  Encrypt the connection to your database
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setForm({ ...form, ssl: !form.ssl })}
              className={`relative w-10 h-5.5 rounded-full transition-colors duration-200 ${
                form.ssl
                  ? "bg-[var(--color-accent)]"
                  : "bg-[var(--color-border-hover)]"
              }`}
            >
              <span
                className={`absolute top-0.5 w-4.5 h-4.5 rounded-full bg-white transition-transform duration-200 ${
                  form.ssl ? "translate-x-5" : "translate-x-0.5"
                }`}
              />
            </button>
          </div>

          {/* Description (optional) */}
          <div>
            <label className="block text-xs font-medium text-[var(--color-text-muted)] mb-1.5">
              Description{" "}
              <span className="text-[var(--color-text-dim)]">(optional)</span>
            </label>
            <input
              type="text"
              placeholder="e.g. Production analytics warehouse, read replica"
              value={form.description}
              onChange={(e) =>
                setForm({ ...form, description: e.target.value })
              }
              className="w-full px-3 py-2.5 rounded-lg bg-[var(--color-bg-input)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent)] focus:ring-1 focus:ring-[var(--color-accent)]/30 transition-all"
            />
          </div>

          {/* Info banner */}
          <div className="flex items-start gap-3 p-3 rounded-lg bg-[var(--color-accent)]/5 border border-[var(--color-accent)]/15">
            <Info className="w-4 h-4 text-[var(--color-accent)] flex-shrink-0 mt-0.5" />
            <p className="text-xs text-[var(--color-text-muted)] leading-relaxed">
              Credentials are stored in memory only and never written to disk in
              plain text. All queries are executed in read-only transactions
              with SQL governance.
            </p>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-3 pt-2">
            <button
              onClick={handleTestAndSave}
              disabled={!isFormValid || saving}
              className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-[var(--color-accent)] hover:bg-[var(--color-accent-hover)] text-white text-sm font-medium transition-all disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {saving ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Zap className="w-4 h-4" />
              )}
              Test & Save Connection
            </button>
            <button
              onClick={resetForm}
              className="px-4 py-2.5 rounded-lg text-sm text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)] transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      </div>
    );
  }

  /* ─── Wizard: Testing / Error State ─────────────────────────────────── */

  if (step === "testing" && wizardTestResult) {
    const isError = wizardTestResult.status !== "healthy";
    return (
      <div className="p-8 max-w-2xl mx-auto">
        <div className="text-center py-12">
          {isError ? (
            <>
              <div className="w-16 h-16 rounded-full bg-[var(--color-error)]/10 flex items-center justify-center mx-auto mb-5">
                <XCircle className="w-8 h-8 text-[var(--color-error)]" />
              </div>
              <h2 className="text-lg font-semibold mb-2">
                Connection test failed
              </h2>
              <p className="text-sm text-[var(--color-text-muted)] mb-4 max-w-md mx-auto">
                {wizardTestResult.message}
              </p>
              {wizardTestResult.error_hint && (
                <div className="inline-flex items-start gap-2 p-3 rounded-lg bg-[var(--color-warning)]/8 border border-[var(--color-warning)]/20 text-left max-w-md mb-6">
                  <AlertCircle className="w-4 h-4 text-[var(--color-warning)] flex-shrink-0 mt-0.5" />
                  <p className="text-xs text-[var(--color-text-muted)]">
                    {wizardTestResult.error_hint}
                  </p>
                </div>
              )}
              <div className="flex items-center gap-3 justify-center">
                <button
                  onClick={() => setStep("configure")}
                  className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[var(--color-accent)] hover:bg-[var(--color-accent-hover)] text-white text-sm font-medium transition-colors"
                >
                  <ArrowLeft className="w-4 h-4" /> Edit Configuration
                </button>
                <button
                  onClick={resetForm}
                  className="px-4 py-2 rounded-lg text-sm text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)] transition-colors"
                >
                  Cancel
                </button>
              </div>
            </>
          ) : (
            <Loader2 className="w-8 h-8 animate-spin text-[var(--color-accent)] mx-auto" />
          )}
        </div>
      </div>
    );
  }

  if (step === "testing" && !wizardTestResult) {
    return (
      <div className="p-8 max-w-2xl mx-auto">
        <div className="text-center py-16">
          <div className="relative w-16 h-16 mx-auto mb-6">
            <div className="absolute inset-0 rounded-full border-2 border-[var(--color-accent)]/20" />
            <div className="absolute inset-0 rounded-full border-2 border-[var(--color-accent)] border-t-transparent animate-spin" />
            <div className="absolute inset-3 rounded-full bg-[var(--color-accent)]/10 flex items-center justify-center">
              {selectedDbType?.icon}
            </div>
          </div>
          <h2 className="text-lg font-semibold mb-2">
            Connecting to {selectedDbType?.name}...
          </h2>
          <p className="text-sm text-[var(--color-text-muted)]">
            Testing connection to {form.host}:{form.port}/{form.database}
          </p>
        </div>
      </div>
    );
  }

  /* ─── Wizard: Success ───────────────────────────────────────────────── */

  if (step === "success" && wizardTestResult) {
    return (
      <div className="p-8 max-w-2xl mx-auto">
        <div className="text-center mb-8">
          <div className="w-16 h-16 rounded-full bg-[var(--color-success)]/10 flex items-center justify-center mx-auto mb-5 animate-[scale-in_0.3s_ease-out]">
            <CheckCircle2 className="w-8 h-8 text-[var(--color-success)]" />
          </div>
          <h2 className="text-lg font-semibold mb-1">
            Connected successfully
          </h2>
          <p className="text-sm text-[var(--color-text-muted)]">
            {form.name} is ready to use
          </p>
        </div>

        {/* Connection diagnostics card */}
        <div className="p-5 rounded-xl bg-[var(--color-bg-card)] border border-[var(--color-border)] mb-6">
          <div className="grid grid-cols-2 gap-4 mb-5">
            {wizardTestResult.latency_ms != null && (
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-[var(--color-success)]/10 flex items-center justify-center">
                  <Zap className="w-4 h-4 text-[var(--color-success)]" />
                </div>
                <div>
                  <p className="text-xs text-[var(--color-text-dim)]">
                    Latency
                  </p>
                  <p className="text-sm font-medium">
                    {wizardTestResult.latency_ms.toFixed(1)}ms
                  </p>
                </div>
              </div>
            )}
            {wizardTestResult.table_count != null && (
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-[var(--color-accent)]/10 flex items-center justify-center">
                  <Table2 className="w-4 h-4 text-[var(--color-accent)]" />
                </div>
                <div>
                  <p className="text-xs text-[var(--color-text-dim)]">Tables</p>
                  <p className="text-sm font-medium">
                    {wizardTestResult.table_count}
                  </p>
                </div>
              </div>
            )}
            {wizardTestResult.server_version && (
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-[var(--color-warning)]/10 flex items-center justify-center">
                  <Server className="w-4 h-4 text-[var(--color-warning)]" />
                </div>
                <div>
                  <p className="text-xs text-[var(--color-text-dim)]">
                    Server
                  </p>
                  <p className="text-sm font-medium truncate max-w-[200px]">
                    {wizardTestResult.server_version.split(" ").slice(0, 2).join(" ")}
                  </p>
                </div>
              </div>
            )}
            {wizardTestResult.ssl_active != null && (
              <div className="flex items-center gap-3">
                <div
                  className={`w-8 h-8 rounded-lg flex items-center justify-center ${
                    wizardTestResult.ssl_active
                      ? "bg-[var(--color-success)]/10"
                      : "bg-[var(--color-bg-hover)]"
                  }`}
                >
                  <Shield
                    className={`w-4 h-4 ${
                      wizardTestResult.ssl_active
                        ? "text-[var(--color-success)]"
                        : "text-[var(--color-text-dim)]"
                    }`}
                  />
                </div>
                <div>
                  <p className="text-xs text-[var(--color-text-dim)]">SSL</p>
                  <p className="text-sm font-medium">
                    {wizardTestResult.ssl_active ? "Active" : "Off"}
                  </p>
                </div>
              </div>
            )}
          </div>

          {/* Schema preview table */}
          {wizardTestResult.schema_preview &&
            wizardTestResult.schema_preview.length > 0 && (
              <div className="border-t border-[var(--color-border)] pt-4">
                <div className="flex items-center gap-2 mb-3">
                  <Layers className="w-3.5 h-3.5 text-[var(--color-text-dim)]" />
                  <span className="text-xs font-medium text-[var(--color-text-muted)]">
                    Schema Preview
                  </span>
                </div>
                <div className="rounded-lg overflow-hidden border border-[var(--color-border)]">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="bg-[var(--color-bg)]">
                        <th className="text-left px-3 py-2 text-[var(--color-text-dim)] font-medium">
                          Table
                        </th>
                        <th className="text-left px-3 py-2 text-[var(--color-text-dim)] font-medium">
                          Schema
                        </th>
                        <th className="text-right px-3 py-2 text-[var(--color-text-dim)] font-medium">
                          Columns
                        </th>
                        <th className="text-right px-3 py-2 text-[var(--color-text-dim)] font-medium">
                          Size
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {wizardTestResult.schema_preview.map((t, i) => (
                        <tr
                          key={i}
                          className="border-t border-[var(--color-border)]"
                        >
                          <td className="px-3 py-2 font-mono text-[var(--color-text)]">
                            {t.table}
                          </td>
                          <td className="px-3 py-2 text-[var(--color-text-muted)]">
                            {t.schema}
                          </td>
                          <td className="px-3 py-2 text-right text-[var(--color-text-muted)]">
                            {t.columns}
                          </td>
                          <td className="px-3 py-2 text-right text-[var(--color-text-muted)]">
                            {t.size}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {wizardTestResult.table_count &&
                  wizardTestResult.schema_preview.length <
                    wizardTestResult.table_count && (
                    <p className="text-[11px] text-[var(--color-text-dim)] mt-2">
                      Showing {wizardTestResult.schema_preview.length} of{" "}
                      {wizardTestResult.table_count} tables
                    </p>
                  )}
              </div>
            )}
        </div>

        <div className="flex items-center gap-3 justify-center">
          <button
            onClick={resetForm}
            className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-[var(--color-accent)] hover:bg-[var(--color-accent-hover)] text-white text-sm font-medium transition-colors"
          >
            Done
          </button>
          <button
            onClick={() => {
              resetForm();
              setStep("select_type");
            }}
            className="px-4 py-2.5 rounded-lg text-sm text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)] transition-colors"
          >
            Add Another
          </button>
        </div>
      </div>
    );
  }

  /* ─── Main: Connection List ─────────────────────────────────────────── */

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-semibold mb-1">Data Connections</h1>
          <p className="text-sm text-[var(--color-text-muted)]">
            Manage database connections for governed AI access
          </p>
        </div>
        <button
          onClick={() => setStep("select_type")}
          className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-[var(--color-accent)] hover:bg-[var(--color-accent-hover)] text-white text-sm font-medium transition-all hover:shadow-lg hover:shadow-[var(--color-accent)]/20"
        >
          <Plus className="w-4 h-4" /> Add Connection
        </button>
      </div>

      {/* Connection cards */}
      {connections.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <div className="w-20 h-20 rounded-2xl bg-[var(--color-bg-card)] border border-[var(--color-border)] flex items-center justify-center mb-5">
            <Database className="w-8 h-8 text-[var(--color-text-dim)]" />
          </div>
          <h3 className="text-base font-medium mb-2">No connections yet</h3>
          <p className="text-sm text-[var(--color-text-muted)] mb-6 max-w-sm">
            Connect your databases to enable governed SQL queries and AI-powered
            analysis
          </p>
          <button
            onClick={() => setStep("select_type")}
            className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-[var(--color-accent)] hover:bg-[var(--color-accent-hover)] text-white text-sm font-medium transition-all hover:shadow-lg hover:shadow-[var(--color-accent)]/20"
          >
            <Plus className="w-4 h-4" /> Add your first connection
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {connections.map((conn) => {
            const dbType = DB_TYPES.find((d) => d.type === conn.db_type);
            const result = testResults[conn.name];
            const isExpanded = expandedCard === conn.name;
            const isTesting = testing === conn.name;
            const statusColor =
              conn.status === "healthy"
                ? "var(--color-success)"
                : conn.status === "error"
                  ? "var(--color-error)"
                  : "var(--color-text-dim)";

            return (
              <div
                key={conn.id}
                className="bg-[var(--color-bg-card)] border border-[var(--color-border)] rounded-xl overflow-hidden hover:border-[var(--color-border-hover)] transition-all"
              >
                {/* Main row */}
                <div className="flex items-center gap-4 p-4">
                  {/* DB Icon */}
                  <div
                    className="w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0"
                    style={{
                      backgroundColor: dbType?.lightColor || "var(--color-bg-hover)",
                    }}
                  >
                    {dbType?.icon || (
                      <Database className="w-5 h-5 text-[var(--color-text-dim)]" />
                    )}
                  </div>

                  {/* Info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2.5">
                      <span className="font-medium text-sm">{conn.name}</span>
                      <span
                        className="text-[10px] px-2 py-0.5 rounded-full font-medium uppercase tracking-wider"
                        style={{
                          backgroundColor: dbType?.lightColor || "var(--color-bg-hover)",
                          color: dbType?.color || "var(--color-text-muted)",
                        }}
                      >
                        {dbType?.name || conn.db_type}
                      </span>
                      {/* Status dot */}
                      <span className="flex items-center gap-1">
                        <span
                          className="w-1.5 h-1.5 rounded-full"
                          style={{ backgroundColor: statusColor }}
                        />
                      </span>
                    </div>
                    <div className="text-xs text-[var(--color-text-muted)] mt-0.5 flex items-center gap-1.5">
                      <span>
                        {conn.host}:{conn.port}/{conn.database}
                      </span>
                      {conn.description && (
                        <>
                          <span className="text-[var(--color-text-dim)]">
                            &middot;
                          </span>
                          <span className="text-[var(--color-text-dim)]">
                            {conn.description}
                          </span>
                        </>
                      )}
                    </div>
                  </div>

                  {/* Test result inline */}
                  {result && (
                    <div
                      className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-lg ${
                        result.status === "healthy"
                          ? "bg-[var(--color-success)]/10 text-[var(--color-success)]"
                          : "bg-[var(--color-error)]/10 text-[var(--color-error)]"
                      }`}
                    >
                      {result.status === "healthy" ? (
                        <CheckCircle2 className="w-3 h-3" />
                      ) : (
                        <XCircle className="w-3 h-3" />
                      )}
                      {result.status === "healthy"
                        ? `${result.latency_ms?.toFixed(0) || ""}ms`
                        : "Failed"}
                    </div>
                  )}

                  {/* Actions */}
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => handleTestExisting(conn.name)}
                      disabled={isTesting}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-[var(--color-text-muted)] hover:text-[var(--color-accent)] hover:bg-[var(--color-accent)]/8 transition-all"
                      title="Test connection"
                    >
                      {isTesting ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <TestTube className="w-3.5 h-3.5" />
                      )}
                      Test
                    </button>
                    {result && result.status === "healthy" && (
                      <button
                        onClick={() =>
                          setExpandedCard(isExpanded ? null : conn.name)
                        }
                        className="flex items-center gap-1 px-2 py-1.5 rounded-lg text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-hover)] transition-all"
                        title="Show details"
                      >
                        {isExpanded ? (
                          <ChevronUp className="w-3.5 h-3.5" />
                        ) : (
                          <ChevronDown className="w-3.5 h-3.5" />
                        )}
                      </button>
                    )}
                    {deleteConfirm === conn.name ? (
                      <div className="flex items-center gap-1 ml-1">
                        <button
                          onClick={() => handleDelete(conn.name)}
                          className="px-2 py-1 rounded text-xs bg-[var(--color-error)]/15 text-[var(--color-error)] hover:bg-[var(--color-error)]/25 transition-colors"
                        >
                          Confirm
                        </button>
                        <button
                          onClick={() => setDeleteConfirm(null)}
                          className="px-2 py-1 rounded text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text-muted)] transition-colors"
                        >
                          <X className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setDeleteConfirm(conn.name)}
                        className="p-1.5 rounded-lg hover:bg-[var(--color-error)]/10 text-[var(--color-text-dim)] hover:text-[var(--color-error)] transition-all"
                        title="Delete connection"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                </div>

                {/* Expanded details panel */}
                {isExpanded && result && result.status === "healthy" && (
                  <div className="border-t border-[var(--color-border)] p-4 bg-[var(--color-bg)]/50">
                    <div className="grid grid-cols-4 gap-4 mb-4">
                      {result.latency_ms != null && (
                        <div>
                          <p className="text-[11px] text-[var(--color-text-dim)] mb-0.5">
                            Latency
                          </p>
                          <p className="text-sm font-medium flex items-center gap-1.5">
                            <Zap className="w-3 h-3 text-[var(--color-success)]" />
                            {result.latency_ms.toFixed(1)}ms
                          </p>
                        </div>
                      )}
                      {result.table_count != null && (
                        <div>
                          <p className="text-[11px] text-[var(--color-text-dim)] mb-0.5">
                            Tables
                          </p>
                          <p className="text-sm font-medium flex items-center gap-1.5">
                            <Table2 className="w-3 h-3 text-[var(--color-accent)]" />
                            {result.table_count}
                          </p>
                        </div>
                      )}
                      {result.server_version && (
                        <div>
                          <p className="text-[11px] text-[var(--color-text-dim)] mb-0.5">
                            Server
                          </p>
                          <p className="text-sm font-medium truncate">
                            {result.server_version
                              .split(" ")
                              .slice(0, 2)
                              .join(" ")}
                          </p>
                        </div>
                      )}
                      {result.current_connections != null &&
                        result.max_connections != null && (
                          <div>
                            <p className="text-[11px] text-[var(--color-text-dim)] mb-0.5">
                              Connections
                            </p>
                            <p className="text-sm font-medium">
                              {result.current_connections} /{" "}
                              {result.max_connections}
                            </p>
                          </div>
                        )}
                    </div>

                    {/* Schema preview */}
                    {result.schema_preview &&
                      result.schema_preview.length > 0 && (
                        <div>
                          <div className="flex items-center gap-2 mb-2">
                            <Layers className="w-3 h-3 text-[var(--color-text-dim)]" />
                            <span className="text-[11px] font-medium text-[var(--color-text-muted)]">
                              Schema Preview
                            </span>
                          </div>
                          <div className="rounded-lg overflow-hidden border border-[var(--color-border)]">
                            <table className="w-full text-xs">
                              <thead>
                                <tr className="bg-[var(--color-bg)]">
                                  <th className="text-left px-3 py-1.5 text-[var(--color-text-dim)] font-medium">
                                    Table
                                  </th>
                                  <th className="text-left px-3 py-1.5 text-[var(--color-text-dim)] font-medium">
                                    Schema
                                  </th>
                                  <th className="text-right px-3 py-1.5 text-[var(--color-text-dim)] font-medium">
                                    Columns
                                  </th>
                                  <th className="text-right px-3 py-1.5 text-[var(--color-text-dim)] font-medium">
                                    Size
                                  </th>
                                </tr>
                              </thead>
                              <tbody>
                                {result.schema_preview.map(
                                  (t: any, i: number) => (
                                    <tr
                                      key={i}
                                      className="border-t border-[var(--color-border)]"
                                    >
                                      <td className="px-3 py-1.5 font-mono text-[var(--color-text)]">
                                        {t.table}
                                      </td>
                                      <td className="px-3 py-1.5 text-[var(--color-text-muted)]">
                                        {t.schema}
                                      </td>
                                      <td className="px-3 py-1.5 text-right text-[var(--color-text-muted)]">
                                        {t.columns}
                                      </td>
                                      <td className="px-3 py-1.5 text-right text-[var(--color-text-muted)]">
                                        {t.size}
                                      </td>
                                    </tr>
                                  )
                                )}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      )}
                  </div>
                )}

                {/* Expanded error details */}
                {isExpanded && result && result.status !== "healthy" && (
                  <div className="border-t border-[var(--color-border)] p-4 bg-[var(--color-error)]/3">
                    <p className="text-xs text-[var(--color-error)] mb-1">
                      {result.message}
                    </p>
                    {result.error_hint && (
                      <p className="text-xs text-[var(--color-text-muted)]">
                        {result.error_hint}
                      </p>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
