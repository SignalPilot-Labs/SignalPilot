import { AlertTriangleIcon, CloudIcon, DatabaseIcon, FolderPlusIcon, Loader2Icon, RefreshCwIcon, Trash2Icon, XIcon } from "lucide-react";
import { preconnectKernel } from "@/utils/preconnect";
import type React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { navigate } from "@/embed/host-navigate";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/use-toast";
import { setGatewayBranchId, setGatewayProjectId } from "@/core/network/api";
import { dbtProjectDirAtom } from "../editor/dbt/use-dbt";
import { Header } from "./components";
import { store } from "@/core/state/jotai";
import { gatewayUrlAtom, gatewayApiKeyAtom } from "@/core/meta/state";
import { cn } from "@/utils/cn";
import { timeAgo } from "@/utils/dates";

interface GatewayProject {
  id: string;
  name: string;
  display_name: string;
  description: string;
  connection_name: string | null;
  default_branch: string | null;
  status: string;
  tags: string[];
  file_count: number;
  total_bytes: number;
  created_at: number;
  updated_at: number;
}

interface Props {
  onRefresh?: () => void;
}

function getGatewayConfig(): { url: string; key: string } {
  return {
    url: store.get(gatewayUrlAtom) || localStorage.getItem("sp:gateway-url") || "http://localhost:3300",
    key: store.get(gatewayApiKeyAtom) || localStorage.getItem("sp:api-key") || "",
  };
}

function gatewayHeaders(key: string): Record<string, string> {
  if (!key) {return {};}
  // JWTs contain dots (header.payload.signature); sp_ keys don't
  if (key.includes(".")) {return { Authorization: `Bearer ${key}` };}
  return { "X-API-Key": key };
}

async function fetchGatewayProjects(): Promise<GatewayProject[]> {
  const { url: gatewayUrl, key: apiKey } = getGatewayConfig();

  const resp = await fetch(`${gatewayUrl}/api/workspace-projects?status=active&limit=50`, {
    headers: gatewayHeaders(apiKey),
  });
  if (!resp.ok) {
    throw new Error(`Gateway error: ${resp.status}`);
  }
  const data = await resp.json() as { projects?: GatewayProject[] };
  return data.projects || [];
}

export const DbtProjectList: React.FC<Props> = ({ onRefresh }) => {
  const [projects, setProjects] = useState<GatewayProject[]>([]);
  const [loading, setLoading] = useState(true);
  const [showImport, setShowImport] = useState(false);
  const [importPath, setImportPath] = useState("");
  const importInputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const gatewayProjects = await fetchGatewayProjects();
      setProjects(gatewayProjects);
    } catch (e) {
      toast({
        title: "Error",
        description: `Failed to load projects: ${(e as Error).message}`,
        variant: "danger",
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleProjectClick = async (project: GatewayProject) => {
    setGatewayProjectId(project.id);
    store.set(dbtProjectDirAtom, null);

    // Branch state is local git — no server-side user-session endpoint.
    // Default to the project's default branch; user switches locally via git.
    const activeBranch = project.default_branch || "main";

    setGatewayBranchId(activeBranch);
    localStorage.removeItem("sp:file-tree-cache");
    localStorage.removeItem("sp:file-tree-open-state");
    const base = new URL(window.location.href);
    base.search = "";
    base.searchParams.set("project", project.id);
    base.searchParams.set("branch", activeBranch);
    base.searchParams.set("file", "__new__project");
    navigate(base.pathname + base.search);
  };

  const handleImport = () => {
    const path = importPath.trim();
    if (!path) {return;}
    store.set(dbtProjectDirAtom, path);
    setGatewayProjectId(null);
    const base = new URL(window.location.href);
    base.search = "";
    base.searchParams.set("file", "__new__project");
    navigate(base.pathname + base.search);
  };

  const handleRefresh = () => {
    refresh();
    onRefresh?.();
  };

  useEffect(() => {
    if (showImport) {
      importInputRef.current?.focus();
    }
  }, [showImport]);

  return (
    <div>
      <Header
        Icon={DatabaseIcon}
        control={
          <div className="flex items-center gap-1">
            <Button
              variant="text"
              size="xs"
              onClick={() => setShowImport(!showImport)}
              title="Import local project"
            >
              <FolderPlusIcon size={14} />
            </Button>
            <Button
              variant="text"
              size="xs"
              onClick={handleRefresh}
              disabled={loading}
            >
              {loading ? (
                <Loader2Icon size={14} className="animate-spin" />
              ) : (
                <RefreshCwIcon size={14} />
              )}
            </Button>
          </div>
        }
      >
        Projects
      </Header>

      {showImport && (
        <div className="flex items-center gap-2 mt-2 mb-3 px-1">
          <input
            ref={importInputRef}
            type="text"
            value={importPath}
            onChange={(e) => setImportPath(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") {handleImport();} }}
            placeholder="Paste path to local dbt project folder..."
            className="flex-1 rounded-md border border-border bg-background px-3 py-1.5 text-sm placeholder:text-muted-foreground/60 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/40"
          />
          <Button
            variant="default"
            size="sm"
            onClick={handleImport}
            disabled={!importPath.trim()}
          >
            Open
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => { setShowImport(false); setImportPath(""); }}
          >
            Cancel
          </Button>
        </div>
      )}

      {loading && projects.length === 0 ? (
        <div className="flex items-center justify-center py-12 text-muted-foreground text-sm">
          <Loader2Icon size={16} className="animate-spin mr-2" />
          Loading projects...
        </div>
      ) : projects.length === 0 ? (
        <div className="py-8 text-center text-muted-foreground text-sm">
          <CloudIcon size={24} className="mx-auto mb-2 opacity-40" />
          <p>No projects found.</p>
          <p className="text-xs mt-1">
            Click <FolderPlusIcon size={12} className="inline" /> to import a local project.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mt-2">
          {projects.map((project) => (
            <GatewayProjectCard
              key={project.id}
              project={project}
              onClick={handleProjectClick}
              onDeleted={refresh}
            />
          ))}
        </div>
      )}
    </div>
  );
};

const GatewayProjectCard: React.FC<{
  project: GatewayProject;
  onClick: (project: GatewayProject) => void;
  onDeleted?: () => void;
}> = ({ project, onClick, onDeleted }) => {
  const [showDelete, setShowDelete] = useState(false);

  return (
    <>
      <div
        className={cn(
          "w-full text-left p-4 rounded-lg border border-border relative",
          "hover:border-primary/40 hover:bg-muted/50 transition-all duration-150",
          "cursor-pointer group",
        )}
        onMouseEnter={preconnectKernel}
        onFocus={preconnectKernel}
        onClick={() => onClick(project)}
      >
        <div className="flex items-start gap-3">
          <div className="mt-0.5 p-2 rounded-md bg-primary/10 text-primary">
            <CloudIcon size={18} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="font-semibold text-sm truncate">
              {project.display_name || project.name}
            </div>
            {project.description && (
              <div className="text-xs text-muted-foreground mt-0.5 truncate">
                {project.description}
              </div>
            )}
            {project.connection_name && (
              <div className="text-xs text-muted-foreground mt-0.5">
                <DatabaseIcon size={10} className="inline mr-1" />
                {project.connection_name}
              </div>
            )}
            <div className="flex items-center gap-3 text-[10px] text-muted-foreground mt-1.5">
              {project.file_count > 0 && (
                <span>{project.file_count} files</span>
              )}
              {project.updated_at && (
                <span>{timeAgo(project.updated_at * 1000, navigator.language)}</span>
              )}
            </div>
            {project.tags.length > 0 && (
              <div className="flex gap-1 mt-1.5 flex-wrap">
                {project.tags.map((tag) => (
                  <span
                    key={tag}
                    className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
        {/* Delete button — only visible on hover */}
        <button
          type="button"
          className="absolute top-2 right-2 p-1.5 rounded-md opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-destructive hover:bg-destructive/10"
          onClick={(e) => {
            e.stopPropagation();
            setShowDelete(true);
          }}
        >
          <Trash2Icon size={14} />
        </button>
      </div>
      {showDelete && (
        <DeleteProjectModal
          project={project}
          onClose={() => setShowDelete(false)}
          onDeleted={() => {
            setShowDelete(false);
            onDeleted?.();
          }}
        />
      )}
    </>
  );
};

const DeleteProjectModal: React.FC<{
  project: GatewayProject;
  onClose: () => void;
  onDeleted: () => void;
}> = ({ project, onClose, onDeleted }) => {
  const [confirmText, setConfirmText] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const projectName = project.display_name || project.name;
  const confirmPhrase = `delete ${projectName}`;
  const isConfirmed = confirmText.toLowerCase() === confirmPhrase.toLowerCase();

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleDelete = async () => {
    if (!isConfirmed) {return;}
    setDeleting(true);
    setError("");

    try {
      const { url: gatewayUrl, key: apiKey } = getGatewayConfig();
      const resp = await fetch(
        `${gatewayUrl}/api/workspace-projects/${project.id}`,
        {
          method: "DELETE",
          headers: gatewayHeaders(apiKey),
        },
      );
      if (resp.ok || resp.status === 204) {
        toast({ title: "Project deleted", description: `${projectName} has been permanently deleted.` });
        onDeleted();
      } else {
        const data = await resp.text().catch(() => "");
        setError(`Failed to delete: ${data || resp.statusText}`);
      }
    } catch (e) {
      setError(String(e));
    }
    setDeleting(false);
  };

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div
        className="w-full max-w-md mx-4 rounded-xl border border-border bg-background shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center gap-3 px-5 py-4 border-b border-destructive/20 bg-destructive/5">
          <div className="p-2 rounded-full bg-destructive/10">
            <AlertTriangleIcon size={20} className="text-destructive" />
          </div>
          <div className="flex-1">
            <h3 className="text-sm font-semibold text-foreground">Delete Project</h3>
            <p className="text-xs text-muted-foreground">This action cannot be undone</p>
          </div>
          <button type="button" onClick={onClose} className="p-1 rounded hover:bg-muted/50 text-muted-foreground">
            <XIcon size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 space-y-4">
          <div className="text-sm text-foreground/80">
            This will permanently delete <span className="font-semibold text-foreground">{projectName}</span>, including
            all branches, files, and commit history. This cannot be reversed.
          </div>

          <div className="space-y-2">
            <label className="text-xs text-muted-foreground font-medium">
              To confirm, type <span className="font-mono text-foreground bg-muted px-1.5 py-0.5 rounded">{confirmPhrase}</span> below
            </label>
            <input
              ref={inputRef}
              type="text"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && isConfirmed) {handleDelete();} }}
              placeholder={confirmPhrase}
              className={cn(
                "w-full rounded-md border px-3 py-2 text-sm font-mono",
                "bg-background placeholder:text-muted-foreground/30",
                "focus:outline-none focus:ring-2",
                isConfirmed
                  ? "border-destructive/50 focus:ring-destructive/30"
                  : "border-border focus:ring-ring",
              )}
              autoComplete="off"
              spellCheck={false}
            />
          </div>

          {error && (
            <div className="text-xs text-destructive bg-destructive/5 rounded-md px-3 py-2 border border-destructive/20">
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t bg-muted/30">
          <Button variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            size="sm"
            onClick={handleDelete}
            disabled={!isConfirmed || deleting}
            className="gap-1.5"
          >
            {deleting ? <Loader2Icon size={14} className="animate-spin" /> : <Trash2Icon size={14} />}
            Delete project
          </Button>
        </div>
      </div>
    </div>
  );
};
