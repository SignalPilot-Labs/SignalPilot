"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  Trash2,
  Loader2,
  Database,
  Clock,
  FolderOpen,
  FileText,
  HardDrive,
  ArrowLeft,
  Upload,
  Download,
  File,
  X,
} from "lucide-react";
import { getWorkspaceProject, deleteWorkspaceProject, getWorkspaceFiles, deleteWorkspaceFile, getWorkspaceBranches, getUserSession } from "@/lib/api";
import type { WorkspaceProjectInfo, WorkspaceFileInfo } from "@/lib/types";
import { PageHeader } from "@/components/ui/page-header";
import { StatusDot } from "@/components/ui/data-viz";
import { useToast } from "@/components/ui/toast";
import { DestructiveConfirmDialog } from "@/components/ui/destructive-confirm";
import { TimeAgo } from "@/components/ui/time-ago";
import Link from "next/link";

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function fileIcon(key: string) {
  if (key.endsWith(".sql")) return <span className="text-[10px] font-mono text-blue-400">SQL</span>;
  if (key.endsWith(".yml") || key.endsWith(".yaml")) return <span className="text-[10px] font-mono text-yellow-400">YML</span>;
  if (key.endsWith(".py")) return <span className="text-[10px] font-mono text-green-400">PY</span>;
  if (key.endsWith(".md")) return <span className="text-[10px] font-mono text-gray-400">MD</span>;
  return <File className="w-3 h-3 text-[var(--color-text-dim)]" />;
}

export default function ProjectDetailPage() {
  const { toast } = useToast();
  const router = useRouter();
  const params = useParams();
  const projectId = params.id as string;
  const [project, setProject] = useState<WorkspaceProjectInfo | null>(null);
  const [files, setFiles] = useState<WorkspaceFileInfo[]>([]);
  const [activeBranch, setActiveBranch] = useState("main");
  const [showDelete, setShowDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const refresh = useCallback(() => {
    getWorkspaceProject(projectId).then(setProject).catch(() => {});
    getUserSession(projectId).then((s) => {
      setActiveBranch(s.active_branch);
      getWorkspaceFiles(projectId, s.active_branch).then((res) => setFiles(res.files)).catch(() => {});
    }).catch(() => {
      getWorkspaceFiles(projectId, "main").then((res) => setFiles(res.files)).catch(() => {});
    });
  }, [projectId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleDelete() {
    setDeleting(true);
    try {
      await deleteWorkspaceProject(projectId);
      router.push("/projects");
    } catch (e) { toast(String(e), "error"); setDeleting(false); }
  }

  async function handleDeleteFile(key: string) {
    try {
      await deleteWorkspaceFile(projectId, activeBranch, key);
      setFiles((prev) => prev.filter((f) => f.key !== key));
      toast(`deleted ${key}`, "success");
    } catch (e) { toast(String(e), "error"); }
  }

  if (!project) {
    return (
      <div className="p-8 animate-fade-in">
        <div className="flex items-center gap-2 text-xs text-[var(--color-text-dim)]">
          <Loader2 className="w-3.5 h-3.5 animate-spin" /> loading project...
        </div>
      </div>
    );
  }

  return (
    <div className="p-8 animate-fade-in">
      <Link
        href="/projects"
        className="inline-flex items-center gap-1.5 text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider mb-4"
      >
        <ArrowLeft className="w-3 h-3" /> projects
      </Link>

      <PageHeader
        title={project.display_name}
        subtitle="workspace"
        description={project.description || project.name}
        actions={
          <button
            onClick={() => setShowDelete(true)}
            className="flex items-center gap-2 px-4 py-2 text-xs text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-error)] hover:text-[var(--color-error)] transition-all tracking-wider uppercase"
          >
            <Trash2 className="w-3.5 h-3.5" /> delete
          </button>
        }
      />

      <div className="flex items-center gap-3 mb-6">
        <StatusDot status={project.status === "active" ? "healthy" : "warning"} size={6} pulse={false} />
        <span className="text-xs text-[var(--color-text-muted)] uppercase tracking-wider">{project.status}</span>
        {project.connection_name && (
          <span className="px-1.5 py-0.5 border border-[var(--color-border)] text-[11px] tracking-wider">{project.connection_name}</span>
        )}
        {project.tags?.map((tag) => (
          <span key={tag} className="px-1.5 py-0.5 border border-[var(--color-border)] text-[11px] tracking-wider">{tag}</span>
        ))}
      </div>

      {/* Project info */}
      <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-hidden mb-6">
        <div className="px-5 py-3 border-b border-[var(--color-border)]">
          <span className="text-[12px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">project details</span>
        </div>
        <div className="p-5 space-y-3">
          <InfoRow icon={<FolderOpen className="w-3.5 h-3.5" strokeWidth={1.5} />} label="slug" value={project.name} mono />
          {project.connection_name && (
            <InfoRow icon={<Database className="w-3.5 h-3.5" strokeWidth={1.5} />} label="connection" value={project.connection_name} />
          )}
          <InfoRow icon={<HardDrive className="w-3.5 h-3.5" strokeWidth={1.5} />} label="s3 prefix" value={project.s3_prefix} mono />
          <InfoRow icon={<FileText className="w-3.5 h-3.5" strokeWidth={1.5} />} label="files" value={`${project.file_count} files (${formatBytes(project.total_bytes)})`} />
          <InfoRow icon={<Clock className="w-3.5 h-3.5" strokeWidth={1.5} />} label="created" value={<TimeAgo timestamp={project.created_at} live className="tabular-nums" />} />
          <InfoRow icon={<Clock className="w-3.5 h-3.5" strokeWidth={1.5} />} label="updated" value={<TimeAgo timestamp={project.updated_at} live className="tabular-nums" />} />
        </div>
      </div>

      {/* File browser */}
      <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-hidden">
        <div className="px-5 py-3 border-b border-[var(--color-border)] flex items-center justify-between">
          <span className="text-[12px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">files</span>
          <span className="text-[11px] text-[var(--color-text-dim)] tabular-nums">{files.length} files</span>
        </div>
        {files.length === 0 ? (
          <div className="p-8 text-center text-xs text-[var(--color-text-dim)]">no files yet</div>
        ) : (
          <div className="divide-y divide-[var(--color-border)]">
            {files.map((file) => (
              <div key={file.key} className="flex items-center gap-3 px-5 py-2.5 hover:bg-[var(--color-bg-hover)] transition-colors group">
                <span className="w-6 flex-shrink-0 flex items-center justify-center">{fileIcon(file.key)}</span>
                <span className="flex-1 text-xs font-mono text-[var(--color-text)] truncate">{file.key}</span>
                <span className="text-[11px] text-[var(--color-text-dim)] tabular-nums">{formatBytes(file.size)}</span>
                <TimeAgo timestamp={file.last_modified} live className="text-[11px] text-[var(--color-text-dim)] tabular-nums" />
                <button
                  onClick={() => handleDeleteFile(file.key)}
                  className="opacity-0 group-hover:opacity-100 p-0.5 text-[var(--color-text-dim)] hover:text-[var(--color-error)] transition-all"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <DestructiveConfirmDialog
        open={showDelete}
        projectName={project.display_name}
        onConfirm={handleDelete}
        onCancel={() => setShowDelete(false)}
        confirming={deleting}
      />
    </div>
  );
}

function InfoRow({ icon, label, value, mono = false }: { icon: React.ReactNode; label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-center gap-3 text-xs">
      <span className="text-[var(--color-text-dim)]">{icon}</span>
      <span className="text-[var(--color-text-dim)] tracking-wider w-28">{label}</span>
      <span className={`text-[var(--color-text)] ${mono ? "font-mono" : ""}`}>{value}</span>
    </div>
  );
}
