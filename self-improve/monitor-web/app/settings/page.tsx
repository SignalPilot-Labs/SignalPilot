"use client";

import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import Image from "next/image";
import Link from "next/link";
import {
  fetchSettings,
  fetchSettingsStatus,
  updateSettings,
} from "@/lib/settings-api";
import { fetchRepos } from "@/lib/api";
import type { Settings, SettingsStatus, RepoInfo } from "@/lib/types";
import { Button } from "@/components/ui/Button";
import { clsx } from "clsx";

interface FieldConfig {
  key: keyof Settings;
  label: string;
  statusKey: keyof SettingsStatus;
  placeholder: string;
  secret: boolean;
  helpText: string;
}

const FIELDS: FieldConfig[] = [
  {
    key: "claude_token",
    label: "Claude OAuth Token",
    statusKey: "has_claude_token",
    placeholder: "sk-ant-oat01-...",
    secret: true,
    helpText:
      "Run `claude setup-token` in your terminal to generate this token.",
  },
  {
    key: "git_token",
    label: "GitHub Personal Access Token",
    statusKey: "has_git_token",
    placeholder: "ghp_...",
    secret: true,
    helpText:
      "GitHub Settings > Developer settings > Personal access tokens > Fine-grained tokens. Grant Contents + Pull requests read/write on your repo.",
  },
  {
    key: "max_budget_usd",
    label: "Default Max Budget (USD)",
    statusKey: "has_github_repo", // not a real gate, always optional
    placeholder: "50",
    secret: false,
    helpText:
      "Optional. Default max spend per run. Can be overridden when starting a run.",
  },
];

function getApiBase(): string {
  if (typeof window === "undefined") return "http://localhost:3401";
  return `${window.location.protocol}//${window.location.hostname}:3401`;
}

export default function SettingsPage() {
  const [status, setStatus] = useState<SettingsStatus | null>(null);
  const [settings, setSettings] = useState<Settings>({});
  const [edits, setEdits] = useState<Partial<Settings>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showSecrets, setShowSecrets] = useState<Record<string, boolean>>({});

  // Repos
  const [repos, setRepos] = useState<RepoInfo[]>([]);
  const [newRepo, setNewRepo] = useState("");
  const [addingRepo, setAddingRepo] = useState(false);
  const [repoError, setRepoError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchSettingsStatus(), fetchSettings(), fetchRepos()]).then(
      ([s, cfg, r]) => {
        setStatus(s);
        setSettings(cfg);
        setRepos(r);
      },
    );
  }, []);

  const handleSave = async () => {
    const updates: Partial<Settings> = {};
    for (const [k, v] of Object.entries(edits)) {
      if (v && v.trim()) {
        updates[k as keyof Settings] = v.trim();
      }
    }
    if (Object.keys(updates).length === 0) return;

    setSaving(true);
    setError(null);
    try {
      await updateSettings(updates);
      const [s, cfg] = await Promise.all([
        fetchSettingsStatus(),
        fetchSettings(),
      ]);
      setStatus(s);
      setSettings(cfg);
      setEdits({});
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const handleAddRepo = async () => {
    const slug = newRepo.trim();
    if (!slug) return;
    if (!/^[a-zA-Z0-9_.-]+\/[a-zA-Z0-9_.-]+$/.test(slug)) {
      setRepoError("Use owner/repo format (e.g. my-org/my-project)");
      return;
    }
    if (repos.some((r) => r.repo === slug)) {
      setRepoError("Repository already added");
      return;
    }

    setAddingRepo(true);
    setRepoError(null);
    try {
      // Set as active repo (this also adds it to the repos list)
      await updateSettings({ github_repo: slug });
      const r = await fetchRepos();
      setRepos(r);
      setNewRepo("");
      // Refresh status
      const [s, cfg] = await Promise.all([
        fetchSettingsStatus(),
        fetchSettings(),
      ]);
      setStatus(s);
      setSettings(cfg);
    } catch (e) {
      setRepoError(e instanceof Error ? e.message : "Failed to add");
    } finally {
      setAddingRepo(false);
    }
  };

  const handleRemoveRepo = async (slug: string) => {
    try {
      await fetch(`${getApiBase()}/api/repos/${encodeURIComponent(slug)}`, {
        method: "DELETE",
      });
      const r = await fetchRepos();
      setRepos(r);
    } catch {
      // ignore
    }
  };

  const handleSetActive = async (slug: string) => {
    try {
      await fetch(`${getApiBase()}/api/repos/active`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo: slug }),
      });
      const [s, cfg] = await Promise.all([
        fetchSettingsStatus(),
        fetchSettings(),
      ]);
      setStatus(s);
      setSettings(cfg);
    } catch {
      // ignore
    }
  };

  const hasEdits = Object.values(edits).some((v) => v && v.trim());
  const activeRepo = settings.github_repo || "";

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-[#e8e8e8]">
      {/* Header */}
      <div className="border-b border-[#1a1a1a]">
        <div className="max-w-2xl mx-auto px-4 sm:px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Link
              href="/"
              className="flex items-center gap-2 text-[#999] hover:text-[#888] transition-colors"
            >
              <svg
                width="12"
                height="12"
                viewBox="0 0 12 12"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
              >
                <polyline points="8 2 4 6 8 10" />
              </svg>
              <span className="text-[10px]">Dashboard</span>
            </Link>
            <span className="text-[#1a1a1a]">/</span>
            <div className="flex items-center gap-2">
              <div className="flex items-center justify-center h-6 w-6 rounded bg-white/[0.04] border border-white/[0.08]">
                <Image
                  src="/logo.svg"
                  alt="SignalPilot"
                  width={14}
                  height={14}
                />
              </div>
              <h1 className="text-[12px] font-semibold">Settings</h1>
            </div>
          </div>
          {status && (
            <div
              className={clsx(
                "flex items-center gap-1.5 px-2 py-1 rounded text-[9px] font-medium",
                status.configured
                  ? "bg-[#00ff88]/[0.06] text-[#00ff88]"
                  : "bg-[#ffaa00]/[0.06] text-[#ffaa00]",
              )}
            >
              <div
                className={clsx(
                  "w-1.5 h-1.5 rounded-full",
                  status.configured ? "bg-[#00ff88]" : "bg-[#ffaa00]",
                )}
              />
              {status.configured ? "Configured" : "Setup Required"}
            </div>
          )}
        </div>
      </div>

      {/* Content */}
      <div className="max-w-2xl mx-auto px-4 sm:px-6 py-6 sm:py-8">
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="space-y-6"
        >
          {/* Security info */}
          <div className="border border-[#1a1a1a] rounded bg-[#050505] overflow-hidden">
            <div className="flex items-center gap-2 px-3 py-1.5 bg-[#0a0a0a] border-b border-[#1a1a1a]">
              <div className="flex gap-1">
                <span className="h-2 w-2 rounded-full bg-[#ff4444]/30" />
                <span className="h-2 w-2 rounded-full bg-[#ffaa00]/30" />
                <span className="h-2 w-2 rounded-full bg-[#00ff88]/30" />
              </div>
              <span className="text-[9px] text-[#666] font-mono">security</span>
            </div>
            <div className="flex items-start gap-3 px-4 py-3">
              <svg
                width="44"
                height="44"
                viewBox="0 0 32 32"
                fill="none"
                className="shrink-0"
              >
                <path
                  d="M16 2L4 8v8c0 7.2 5.1 13.2 12 15 6.9-1.8 12-7.8 12-15V8L16 2z"
                  stroke="#00ff88"
                  strokeWidth="1"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  opacity="0.4"
                />
                <path
                  d="M16 5L7 9.5v6.5c0 5.6 3.8 10.2 9 11.5 5.2-1.3 9-5.9 9-11.5V9.5L16 5z"
                  fill="#00ff88"
                  opacity="0.03"
                />
                <rect
                  x="12"
                  y="15"
                  width="8"
                  height="6"
                  rx="1"
                  stroke="#00ff88"
                  strokeWidth="1"
                  opacity="0.6"
                />
                <path
                  d="M13.5 15v-2.5a2.5 2.5 0 015 0V15"
                  stroke="#00ff88"
                  strokeWidth="1"
                  strokeLinecap="round"
                  opacity="0.6"
                />
                <circle cx="16" cy="18" r="1" fill="#00ff88" opacity="0.5" />
                <text
                  x="5"
                  y="7"
                  fontSize="3"
                  fill="#00ff88"
                  opacity="0.15"
                  fontFamily="monospace"
                >
                  01
                </text>
                <text
                  x="24"
                  y="7"
                  fontSize="3"
                  fill="#00ff88"
                  opacity="0.15"
                  fontFamily="monospace"
                >
                  10
                </text>
                <text
                  x="3"
                  y="28"
                  fontSize="3"
                  fill="#00ff88"
                  opacity="0.15"
                  fontFamily="monospace"
                >
                  11
                </text>
                <text
                  x="26"
                  y="28"
                  fontSize="3"
                  fill="#00ff88"
                  opacity="0.15"
                  fontFamily="monospace"
                >
                  00
                </text>
              </svg>
              <div className="space-y-1.5 min-w-0">
                <div className="font-mono text-[10px] leading-relaxed">
                  <span className="text-[#00ff88]/60">$</span>{" "}
                  <span className="text-[#aaa]">
                    Credentials encrypted with
                  </span>{" "}
                  <span className="text-[#00ff88]">AES-128 (Fernet)</span>{" "}
                  <span className="text-[#aaa]">before storage.</span>
                </div>
                <div className="font-mono text-[10px] leading-relaxed">
                  <span className="text-[#00ff88]/60">$</span>{" "}
                  <span className="text-[#aaa]">Decrypted</span>{" "}
                  <span className="text-[#ffcc44]">in-memory only</span>{" "}
                  <span className="text-[#aaa]">when starting a run.</span>
                </div>
                <div className="font-mono text-[10px] leading-relaxed">
                  <span className="text-[#00ff88]/60">$</span>{" "}
                  <span className="text-[#aaa]">
                    Master key on Docker volume &mdash;
                  </span>{" "}
                  <span className="text-[#888]">never leaves host.</span>
                </div>
              </div>
            </div>
          </div>

          {/* Repositories Section */}
          <div className="p-4 bg-white/[0.01] border border-[#1a1a1a] rounded-lg">
            <div className="flex items-center justify-between mb-3">
              <label className="text-[10px] font-semibold text-[#ccc]">
                Repositories
              </label>
              <span className="text-[9px] text-[#666]">
                {repos.length} configured
              </span>
            </div>

            {/* Repo list */}
            <div className="space-y-1.5 mb-3">
              <AnimatePresence>
                {repos.map((r) => {
                  const isActive = r.repo === activeRepo;
                  return (
                    <motion.div
                      key={r.repo}
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: "auto" }}
                      exit={{ opacity: 0, height: 0 }}
                      className="flex items-center gap-2 px-2.5 py-2 bg-black/30 rounded border border-[#1a1a1a] group"
                    >
                      {/* Repo icon */}
                      <svg
                        width="12"
                        height="12"
                        viewBox="0 0 16 16"
                        fill="currentColor"
                        className="text-[#666] shrink-0"
                      >
                        <path d="M2 2.5A2.5 2.5 0 0 1 4.5 0h8.75a.75.75 0 0 1 .75.75v12.5a.75.75 0 0 1-.75.75h-2.5a.75.75 0 0 1 0-1.5h1.75v-2h-8a1 1 0 0 0-.714 1.7.75.75 0 1 1-1.072 1.05A2.495 2.495 0 0 1 2 11.5Zm10.5-1h-8a1 1 0 0 0-1 1v6.708A2.486 2.486 0 0 1 4.5 9h8ZM5 12.25a.25.25 0 0 1 .25-.25h3.5a.25.25 0 0 1 .25.25v3.25a.25.25 0 0 1-.4.2l-1.45-1.087a.249.249 0 0 0-.3 0L5.4 15.7a.25.25 0 0 1-.4-.2Z" />
                      </svg>

                      {/* Repo name */}
                      <span className="text-[10px] font-mono text-[#ccc] flex-1 min-w-0 truncate">
                        {r.repo}
                      </span>

                      {/* Run count */}
                      <span className="text-[9px] text-[#666] shrink-0">
                        {r.run_count} run{r.run_count !== 1 ? "s" : ""}
                      </span>

                      {/* Active badge or Set Active button */}
                      {isActive ? (
                        <span className="flex items-center gap-1 text-[9px] text-[#00ff88]/60 shrink-0">
                          <svg
                            width="8"
                            height="8"
                            viewBox="0 0 10 10"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="1.5"
                          >
                            <polyline points="2 5 4 7 8 3" />
                          </svg>
                          Active
                        </span>
                      ) : (
                        <button
                          onClick={() => handleSetActive(r.repo)}
                          className="text-[9px] text-[#888] hover:text-[#00ff88] transition-colors sm:opacity-0 sm:group-hover:opacity-100 shrink-0"
                        >
                          Set Active
                        </button>
                      )}

                      {/* Remove button */}
                      <button
                        onClick={() => handleRemoveRepo(r.repo)}
                        className="text-[#666] hover:text-[#ff4444] transition-colors sm:opacity-0 sm:group-hover:opacity-100 shrink-0"
                        title="Remove repository"
                      >
                        <svg
                          width="10"
                          height="10"
                          viewBox="0 0 10 10"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.5"
                        >
                          <line x1="2" y1="2" x2="8" y2="8" />
                          <line x1="8" y1="2" x2="2" y2="8" />
                        </svg>
                      </button>
                    </motion.div>
                  );
                })}
              </AnimatePresence>

              {repos.length === 0 && (
                <div className="px-2.5 py-3 text-[10px] text-[#666] text-center">
                  No repositories configured yet
                </div>
              )}
            </div>

            {/* Add repo input */}
            <div className="flex gap-2">
              <div className="relative flex-1">
                <input
                  type="text"
                  value={newRepo}
                  onChange={(e) => {
                    setNewRepo(e.target.value);
                    setRepoError(null);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      handleAddRepo();
                    }
                  }}
                  placeholder="owner/repo"
                  className="w-full bg-black/30 border border-[#1a1a1a] rounded px-3 py-2 text-[11px] text-[#ccc] font-mono placeholder-[#666] focus:outline-none focus:border-[#00ff88]/30 transition-all"
                  autoComplete="off"
                  spellCheck={false}
                />
              </div>
              <Button
                variant="success"
                size="md"
                onClick={handleAddRepo}
                disabled={addingRepo || !newRepo.trim()}
              >
                {addingRepo ? "Adding..." : "Add Repo"}
              </Button>
            </div>

            {repoError && (
              <p className="mt-1.5 text-[9px] text-[#ff4444]">{repoError}</p>
            )}

            <p className="mt-2 text-[9px] text-[#999] leading-relaxed">
              Add repositories in{" "}
              <code className="text-[#88ccff] bg-[#88ccff]/[0.06] px-1 py-0.5 rounded text-[9px]">
                owner/repo
              </code>{" "}
              format. The active repo is used when starting new runs. Switch
              between repos using the selector in the dashboard header.
            </p>
          </div>

          {/* Credential Fields (no longer includes github_repo) */}
          {FIELDS.map((field) => {
            const currentValue = settings[field.key] || "";
            const editValue = edits[field.key];
            const isSet =
              field.key !== "max_budget_usd" &&
              status?.[field.statusKey as keyof SettingsStatus];
            const isSecret = field.secret;
            const show = showSecrets[field.key] || false;

            return (
              <div
                key={field.key}
                className="p-4 bg-white/[0.01] border border-[#1a1a1a] rounded-lg"
              >
                <div className="flex items-center justify-between mb-2">
                  <label className="text-[10px] font-semibold text-[#ccc]">
                    {field.label}
                  </label>
                  {isSet && (
                    <span className="flex items-center gap-1 text-[9px] text-[#00ff88]/60">
                      <svg
                        width="10"
                        height="10"
                        viewBox="0 0 10 10"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.5"
                      >
                        <polyline points="2 5 4 7 8 3" />
                      </svg>
                      Set
                    </span>
                  )}
                </div>

                {currentValue && editValue === undefined && (
                  <div className="mb-2 px-2.5 py-1.5 bg-black/30 rounded border border-[#1a1a1a] text-[10px] font-mono text-[#666] flex items-center justify-between overflow-hidden">
                    <span className="truncate min-w-0">{currentValue}</span>
                    <button
                      onClick={() => setEdits({ ...edits, [field.key]: "" })}
                      className="text-[9px] text-[#999] hover:text-[#888] transition-colors ml-2"
                    >
                      Change
                    </button>
                  </div>
                )}

                {(editValue !== undefined || !currentValue) && (
                  <div className="relative">
                    <input
                      type={isSecret && !show ? "password" : "text"}
                      value={editValue || ""}
                      onChange={(e) =>
                        setEdits({ ...edits, [field.key]: e.target.value })
                      }
                      placeholder={field.placeholder}
                      className="w-full bg-black/30 border border-[#1a1a1a] rounded px-3 py-2 text-[11px] text-[#ccc] font-mono placeholder-[#666] focus:outline-none focus:border-[#00ff88]/30 transition-all pr-10"
                      autoComplete="off"
                      spellCheck={false}
                    />
                    {isSecret && (
                      <button
                        type="button"
                        onClick={() =>
                          setShowSecrets({ ...showSecrets, [field.key]: !show })
                        }
                        className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-[#999] hover:text-[#888] transition-colors"
                        tabIndex={-1}
                      >
                        <svg
                          width="12"
                          height="12"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.5"
                        >
                          {show ? (
                            <>
                              <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
                              <line x1="1" y1="1" x2="23" y2="23" />
                            </>
                          ) : (
                            <>
                              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                              <circle cx="12" cy="12" r="3" />
                            </>
                          )}
                        </svg>
                      </button>
                    )}
                    {editValue !== undefined && currentValue && (
                      <button
                        onClick={() => {
                          const next = { ...edits };
                          delete next[field.key];
                          setEdits(next);
                        }}
                        className="absolute right-8 top-1/2 -translate-y-1/2 text-[9px] text-[#999] hover:text-[#888]"
                      >
                        Cancel
                      </button>
                    )}
                  </div>
                )}

                <p className="mt-2 text-[9px] text-[#999] leading-relaxed">
                  {field.helpText}
                </p>
              </div>
            );
          })}

          {/* Save button */}
          <div className="flex items-center justify-between pt-2">
            <div>
              {error && <p className="text-[10px] text-[#ff4444]">{error}</p>}
              {saved && (
                <motion.p
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="text-[10px] text-[#00ff88]"
                >
                  Settings saved and encrypted
                </motion.p>
              )}
            </div>
            <Button
              variant="success"
              size="md"
              onClick={handleSave}
              disabled={saving || !hasEdits}
            >
              {saving ? "Saving..." : "Save Changes"}
            </Button>
          </div>
        </motion.div>
      </div>
    </div>
  );
}
