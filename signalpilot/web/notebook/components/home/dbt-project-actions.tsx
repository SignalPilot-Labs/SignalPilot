import {
  DatabaseIcon,
  ExternalLinkIcon,
  GitBranchIcon,
  Loader2Icon,
  PlusIcon,
} from "lucide-react";
import type React from "react";
import { navigate } from "@/embed/host-navigate";
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/use-toast";
import { setGatewayBranchId, setGatewayProjectId, spApiUrl } from "@/core/network/api";
import { getApiHeaders } from "@/core/network/api-headers";
import { cn } from "@/utils/cn";
import { request } from "~/lib/api";

const GATEWAY_AUTH_URL = process.env.NEXT_PUBLIC_GATEWAY_URL || "http://localhost:3300";

interface Props {
  onProjectCreated: () => void | Promise<void>;
  openProjectOnComplete?: boolean;
  showGitHubImport?: boolean;
}

export const DbtProjectActions: React.FC<Props> = ({
  onProjectCreated,
  openProjectOnComplete = true,
  showGitHubImport = true,
}) => {
  const [showCreate, setShowCreate] = useState(false);
  const [showImport, setShowImport] = useState(false);

  return (
    <div>
      <div className="flex gap-2 flex-wrap">
        <Button
          variant="outline"
          size="sm"
          className="gap-2"
          onClick={() => setShowCreate(!showCreate)}
        >
          <PlusIcon size={14} />
          Create new project
        </Button>
        {showGitHubImport && (
          <Button
            variant="outline"
            size="sm"
            className="gap-2"
            onClick={() => setShowImport(!showImport)}
          >
            <GitBranchIcon size={14} />
            Import from GitHub
          </Button>
        )}
      </div>

      {showCreate && (
        <CreateProjectForm
          onClose={() => setShowCreate(false)}
          onCreated={onProjectCreated}
          openProjectOnComplete={openProjectOnComplete}
        />
      )}
      {showGitHubImport && showImport && (
        <GitHubImportForm
          onClose={() => setShowImport(false)}
          onImported={onProjectCreated}
          openProjectOnComplete={openProjectOnComplete}
        />
      )}
    </div>
  );
};

// ── Create Project Form ──────────────────────────────────────────

const ADAPTERS = [
  { value: "duckdb", label: "DuckDB" },
  { value: "postgres", label: "PostgreSQL" },
  { value: "snowflake", label: "Snowflake" },
  { value: "bigquery", label: "BigQuery" },
  { value: "redshift", label: "Redshift" },
];

const CreateProjectForm: React.FC<{
  onClose: () => void;
  onCreated: () => void | Promise<void>;
  openProjectOnComplete: boolean;
}> = ({ onClose, onCreated, openProjectOnComplete }) => {
  const [name, setName] = useState("");
  const [adapter, setAdapter] = useState("duckdb");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async () => {
    if (!name.trim()) {
      toast({ title: "Error", description: "Project name is required", variant: "danger" });
      return;
    }

    setLoading(true);
    try {
      const slug = name.trim().toLowerCase().replace(/[^a-z0-9_-]/g, "-");

      // 1. Create project on gateway
      const project = await request<{ id: string; default_branch?: string | null }>("/api/workspace-projects", {
        method: "POST",
        body: JSON.stringify({
          name: slug,
          display_name: name.trim(),
          description: `${name.trim()} dbt project (${adapter})`,
          source: "managed",
          tags: ["dbt", adapter],
        }),
      });

      // 2. Scaffold dbt files into the bare repo via the notebook backend
      if (!openProjectOnComplete) {
        toast({
          title: "Project created",
          description: `Created ${name.trim()} (${adapter})`,
        });
        await onCreated();
        onClose();
        return;
      }

      setGatewayProjectId(project.id);
      setGatewayBranchId(project.default_branch || "main");

      const runtimeHeaders = await getApiHeaders();
      runtimeHeaders["X-Gateway-Project-Id"] = project.id;
      runtimeHeaders["X-Gateway-Branch-Id"] = project.default_branch || "main";

      const syncResp = await fetch(spApiUrl("/project/sync-down"), {
        method: "POST",
        headers: runtimeHeaders,
      });
      const syncData = await syncResp.json() as { error?: string; local_dir: string };
      if (syncData.error) {
        throw new Error(`Sync failed: ${syncData.error}`);
      }

      const scaffoldResp = await fetch(spApiUrl("/dbt/scaffold_project"), {
        method: "POST",
        headers: runtimeHeaders,
        body: JSON.stringify({ projectName: slug, adapter, parentDir: syncData.local_dir }),
      });
      const scaffoldData = await scaffoldResp.json() as { success: boolean; error?: string };

      if (scaffoldData.success) {
        await fetch(spApiUrl("/git/stage"), {
          method: "POST",
          headers: runtimeHeaders,
          body: JSON.stringify({ all: true }),
        });
        await fetch(spApiUrl("/git/commit"), {
          method: "POST",
          headers: runtimeHeaders,
          body: JSON.stringify({ message: `Initialize ${name.trim()} dbt project` }),
        });
        await fetch(spApiUrl("/git/push"), {
          method: "POST",
          headers: runtimeHeaders,
        });
      }

      // Brief pause to let git index and filesystem settle before navigating
      await new Promise((r) => setTimeout(r, 1000));

      toast({
        title: "Project created",
        description: `Created ${name.trim()} (${adapter})`,
      });

      localStorage.removeItem("sp:file-tree-cache");
      localStorage.removeItem("sp:file-tree-open-state");
      const base = new URL(window.location.href);
      base.search = "";
      base.searchParams.set("project", project.id);
      base.searchParams.set("branch", project.default_branch || "main");
      base.searchParams.set("file", "__new__project");
      navigate(base.pathname + base.search);
    } catch (error) {
      toast({
        title: "Error",
        description: error instanceof Error ? error.message : "Unknown error",
        variant: "danger",
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mt-3 p-4 border border-border rounded-lg bg-muted/30 space-y-3">
      <div className="text-sm font-semibold flex items-center gap-2">
        <DatabaseIcon size={14} />
        Create new dbt project
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground font-medium">
            Project name
          </label>
          <input
            type="text"
            className="w-full text-sm bg-background rounded px-3 py-1.5 border border-border focus:outline-none focus:ring-1 focus:ring-ring"
            placeholder="my_dbt_project"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {handleSubmit();}
            }}
            autoFocus={true}
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground font-medium">
            Adapter
          </label>
          <select
            className="w-full text-sm bg-background rounded px-3 py-1.5 border border-border focus:outline-none focus:ring-1 focus:ring-ring"
            value={adapter}
            onChange={(e) => setAdapter(e.target.value)}
          >
            {ADAPTERS.map((a) => (
              <option key={a.value} value={a.value}>
                {a.label}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="flex gap-2 justify-end">
        <Button variant="outline" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <Button size="sm" onClick={handleSubmit} disabled={loading}>
          {loading && <Loader2Icon size={14} className="animate-spin mr-1" />}
          Create
        </Button>
      </div>
    </div>
  );
};

// ── GitHub Import Form ──────────────────────────────────────────

interface GitHubRepo {
  id: number;
  full_name: string;
  name: string;
  private: boolean;
  default_branch: string;
  description: string | null;
  html_url: string;
}

interface GitHubInstallation {
  id: string;
  github_installation_id: number;
  github_account_login: string;
  github_account_type: string;
  status: string;
}

const GitHubImportForm: React.FC<{
  onClose: () => void;
  onImported: () => void | Promise<void>;
  openProjectOnComplete: boolean;
}> = ({ onClose, onImported, openProjectOnComplete }) => {
  const [installations, setInstallations] = useState<GitHubInstallation[]>([]);
  const [repos, setRepos] = useState<GitHubRepo[]>([]);
  const [loadingInstalls, setLoadingInstalls] = useState(true);
  const [loadingRepos, setLoadingRepos] = useState(false);
  const [selectedInstall, setSelectedInstall] = useState<GitHubInstallation | null>(null);
  const [importing, setImporting] = useState<string | null>(null);

  const loadInstallations = useCallback(async () => {
    setLoadingInstalls(true);
    try {
      const data = await request<GitHubInstallation[] | { installations?: GitHubInstallation[] }>("/api/github/installations");
      const installs = Array.isArray(data) ? data : data.installations || [];
      setInstallations(installs);
      if (installs.length === 1) {
        setSelectedInstall(installs[0]);
      }
    } catch {}
    setLoadingInstalls(false);
  }, []);

  useEffect(() => {
    loadInstallations();
  }, [loadInstallations]);

  useEffect(() => {
    if (!selectedInstall) {return;}
    setLoadingRepos(true);
    request<GitHubRepo[] | { repos?: GitHubRepo[] }>(`/api/github/installations/${selectedInstall.id}/repos`)
      .then((data) => setRepos(Array.isArray(data) ? data : data.repos || []))
      .catch(() => setRepos([]))
      .finally(() => setLoadingRepos(false));
  }, [selectedInstall]);

  const handleImportRepo = async (repo: GitHubRepo) => {
    if (!selectedInstall) {return;}
    setImporting(repo.full_name);

    try {
      // Create project on gateway
      const project = await request<{ id: string; default_branch?: string | null }>("/api/workspace-projects", {
        method: "POST",
        body: JSON.stringify({
          name: repo.name,
          display_name: repo.name,
          description: repo.description || "",
          source: "github",
          tags: ["github"],
        }),
      });

      // Link repo to project
      await request<unknown>("/api/github/repo-links", {
        method: "POST",
        body: JSON.stringify({
          project_id: project.id,
          installation_id: selectedInstall.id,
          repo_full_name: repo.full_name,
          repo_id: repo.id,
          default_branch: repo.default_branch,
        }),
      });

      // Tell the gateway to mirror the GitHub repo into its bare git storage
      toast({ title: "Syncing", description: "Mirroring repository from GitHub..." });
      try {
        await request<unknown>(`/api/github/sync/${project.id}`, {
          method: "POST",
        });
      } catch (e) {
        console.warn("[Import] Gateway GitHub sync failed:", e);
      }

      // Sync the project locally before navigating
      if (!openProjectOnComplete) {
        toast({ title: "Imported", description: `${repo.full_name} ready` });
        await onImported();
        onClose();
        return;
      }

      setGatewayProjectId(project.id);
      setGatewayBranchId(repo.default_branch);

      const runtimeHeaders = await getApiHeaders();
      runtimeHeaders["X-Gateway-Project-Id"] = project.id;
      runtimeHeaders["X-Gateway-Branch-Id"] = repo.default_branch;

      // Retry sync-down — gateway may still be mirroring from GitHub
      toast({ title: "Syncing", description: "Cloning repository from GitHub..." });
      let synced = false;
      for (let attempt = 0; attempt < 10; attempt++) {
        try {
          const syncResp = await fetch(spApiUrl("/project/sync-down"), {
            method: "POST",
            headers: runtimeHeaders,
          });
          const syncData = await syncResp.json() as { error?: string; local_dir?: string; file_count?: number };
          if (syncData.local_dir && !syncData.error && syncData.file_count && syncData.file_count > 0) {
            synced = true;
            console.log(`[Import] Synced on attempt ${attempt + 1}: ${syncData.file_count} files`);
            break;
          }
          console.warn(`[Import] Attempt ${attempt + 1}: ${syncData.error ?? `${syncData.file_count ?? 0} files`}`);
        } catch (e) {
          console.warn(`[Import] Attempt ${attempt + 1} failed:`, e);
        }
        await new Promise((r) => setTimeout(r, 2000));
      }

      if (!synced) {
        toast({ title: "Warning", description: "Sync may still be in progress — refresh if the file tree is empty", variant: "danger" });
      } else {
        toast({ title: "Imported", description: `${repo.full_name} ready` });
      }

      await new Promise((r) => setTimeout(r, 500));

      localStorage.removeItem("sp:file-tree-cache");
      localStorage.removeItem("sp:file-tree-open-state");
      const base = new URL(window.location.href);
      base.search = "";
      base.searchParams.set("project", project.id);
      base.searchParams.set("branch", repo.default_branch);
      base.searchParams.set("file", "__new__project");
      navigate(base.pathname + base.search);
    } catch (e) {
      toast({ title: "Error", description: String(e), variant: "danger" });
      setImporting(null);
    }
  };

  const connectUrl = `${GATEWAY_AUTH_URL}/auth/github`;

  return (
    <div className="mt-3 p-4 border border-border rounded-lg bg-muted/30 space-y-3">
      <div className="text-sm font-semibold flex items-center gap-2">
        <GitBranchIcon size={14} />
        Import from GitHub
      </div>

      {loadingInstalls ? (
        <div className="flex items-center justify-center py-6 text-muted-foreground text-xs">
          <Loader2Icon size={14} className="animate-spin mr-2" />
          Loading GitHub connections...
        </div>
      ) : installations.length === 0 ? (
        <div className="text-center py-4 space-y-2">
          <p className="text-sm text-muted-foreground">
            No GitHub account connected.
          </p>
          <a
            href={connectUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-sm text-primary hover:underline"
          >
            Connect GitHub
            <ExternalLinkIcon size={12} />
          </a>
        </div>
      ) : (
        <>
          {installations.length > 1 && (
            <div className="flex gap-2 flex-wrap">
              {installations.map((inst) => (
                <button
                  key={inst.id}
                  type="button"
                  className={cn(
                    "px-3 py-1 rounded-md text-xs border transition-colors",
                    selectedInstall?.id === inst.id
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border text-muted-foreground hover:text-foreground hover:border-foreground/30",
                  )}
                  onClick={() => setSelectedInstall(inst)}
                >
                  {inst.github_account_login}
                </button>
              ))}
            </div>
          )}

          {loadingRepos ? (
            <div className="flex items-center justify-center py-4 text-muted-foreground text-xs">
              <Loader2Icon size={14} className="animate-spin mr-2" />
              Loading repositories...
            </div>
          ) : repos.length === 0 ? (
            <div className="text-center py-4 text-sm text-muted-foreground">
              <p>No repositories found.</p>
              <a
                href={connectUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-xs text-primary hover:underline mt-1"
              >
                Add more repositories
                <ExternalLinkIcon size={10} />
              </a>
            </div>
          ) : (
            <div className="max-h-[240px] overflow-y-auto space-y-1">
              {repos.map((repo) => (
                <div
                  key={repo.id}
                  className="flex items-center gap-3 px-3 py-2 rounded-md border border-border hover:border-primary/30 hover:bg-muted/30 transition-colors"
                >
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium truncate">{repo.full_name}</div>
                    {repo.description && (
                      <div className="text-xs text-muted-foreground truncate">{repo.description}</div>
                    )}
                    <div className="flex items-center gap-2 mt-0.5 text-[10px] text-muted-foreground">
                      <span>{repo.default_branch}</span>
                      {repo.private && <span className="px-1 rounded bg-yellow-500/10 text-yellow-500">private</span>}
                    </div>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    className="shrink-0 text-xs"
                    onClick={() => handleImportRepo(repo)}
                    disabled={importing !== null}
                  >
                    {importing === repo.full_name ? (
                      <Loader2Icon size={12} className="animate-spin mr-1" />
                    ) : null}
                    Import
                  </Button>
                </div>
              ))}
            </div>
          )}

          <div className="flex items-center justify-between pt-2 border-t border-border/50">
            <a
              href={connectUrl}
              target="_blank"
              rel="noopener noreferrer"
            >
              <Button variant="outline" size="sm" className="gap-1.5 text-xs">
                <PlusIcon size={12} />
                Add Repository
                <ExternalLinkIcon size={10} className="opacity-50" />
              </Button>
            </a>
            <Button variant="ghost" size="sm" onClick={onClose}>
              Cancel
            </Button>
          </div>
        </>
      )}
    </div>
  );
};
