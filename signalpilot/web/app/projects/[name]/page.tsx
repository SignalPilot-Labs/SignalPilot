"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  Trash2,
  Loader2,
  RefreshCw,
  Database,
  Clock,
  FolderOpen,
  GitBranch,
  ArrowLeft,
} from "lucide-react";
import { getProject, deleteProject, scanProject } from "@/lib/api";
import type { ProjectInfo } from "@/lib/types";
import { PageHeader } from "@/components/ui/page-header";
import { StatusDot } from "@/components/ui/data-viz";
import { useToast } from "@/components/ui/toast";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { TimeAgo } from "@/components/ui/time-ago";
import Link from "next/link";

export default function ProjectDetailPage() {
  const { toast } = useToast();
  const router = useRouter();
  const params = useParams();
  const name = params.name as string;
  const [project, setProject] = useState<ProjectInfo | null>(null);
  const [scanning, setScanning] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const refresh = useCallback(() => {
    getProject(name).then(setProject).catch(() => {});
  }, [name]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleScan() {
    setScanning(true);
    try {
      const result = await scanProject(name);
      toast(`scan complete: ${result.model_count} models found`, "success");
      refresh();
    } catch (e) { toast(String(e), "error"); }
    finally { setScanning(false); }
  }

  async function handleDelete() {
    setDeleting(true);
    try {
      await deleteProject(name);
      router.push("/projects");
    } catch (e) { toast(String(e), "error"); setDeleting(false); }
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
      {/* Back link */}
      <Link
        href="/projects"
        className="inline-flex items-center gap-1.5 text-xs text-[var(--color-text-dim)] hover:text-[var(--color-text)] transition-colors tracking-wider mb-4"
      >
        <ArrowLeft className="w-3 h-3" /> projects
      </Link>

      <PageHeader
        title={project.name}
        subtitle="dbt"
        description={project.description || `${project.connection_name} / ${project.db_type}`}
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={handleScan}
              disabled={scanning}
              className="flex items-center gap-2 px-4 py-2 text-xs text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-border-hover)] hover:text-[var(--color-text)] transition-all tracking-wider uppercase"
            >
              {scanning ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
              scan
            </button>
            <button
              onClick={() => setShowDelete(true)}
              className="flex items-center gap-2 px-4 py-2 text-xs text-[var(--color-text-dim)] border border-[var(--color-border)] hover:border-[var(--color-error)] hover:text-[var(--color-error)] transition-all tracking-wider uppercase"
            >
              <Trash2 className="w-3.5 h-3.5" /> delete
            </button>
          </div>
        }
      />

      {/* Badges row */}
      <div className="flex items-center gap-3 mb-6">
        <StatusDot
          status={project.status === "active" ? "healthy" : project.status === "error" ? "error" : "warning"}
          size={6}
          pulse={false}
        />
        <span className="text-xs text-[var(--color-text-muted)] uppercase tracking-wider">{project.status}</span>
        <span className="px-1.5 py-0.5 border border-[var(--color-border)] text-[11px] tracking-wider">{project.storage}</span>
        <span className="px-1.5 py-0.5 border border-[var(--color-border)] text-[11px] tracking-wider">{project.source}</span>
        <span className="px-1.5 py-0.5 border border-[var(--color-border)] text-[11px] tracking-wider">{project.db_type}</span>
        <span className="text-xs text-[var(--color-text-dim)] tabular-nums">{project.model_count} models</span>
      </div>

      {/* Info section */}
      <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] overflow-hidden">
        <div className="px-5 py-3 border-b border-[var(--color-border)]">
          <span className="text-[12px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">project details</span>
        </div>
        <div className="p-5 space-y-3">
          <InfoRow icon={<Database className="w-3.5 h-3.5" strokeWidth={1.5} />} label="connection" value={project.connection_name} />
          <InfoRow icon={<FolderOpen className="w-3.5 h-3.5" strokeWidth={1.5} />} label="path" value={project.project_dir} mono />
          <InfoRow icon={<span className="text-[11px] font-mono">dbt</span>} label="dbt version" value={project.dbt_version} />
          {project.git_remote && (
            <InfoRow icon={<GitBranch className="w-3.5 h-3.5" strokeWidth={1.5} />} label="git remote" value={project.git_remote} mono />
          )}
          {project.git_branch && (
            <InfoRow icon={<GitBranch className="w-3.5 h-3.5" strokeWidth={1.5} />} label="git branch" value={project.git_branch} />
          )}
          <InfoRow
            icon={<Clock className="w-3.5 h-3.5" strokeWidth={1.5} />}
            label="created"
            value={<TimeAgo timestamp={project.created_at} live className="tabular-nums" />}
          />
          <InfoRow
            icon={<Clock className="w-3.5 h-3.5" strokeWidth={1.5} />}
            label="last scanned"
            value={project.last_scanned_at ? <TimeAgo timestamp={project.last_scanned_at} live className="tabular-nums" /> : "never"}
          />
        </div>
      </div>

      <ConfirmDialog
        open={showDelete}
        title="delete project"
        message={`this will permanently delete project "${project.name}". this action cannot be undone.`}
        confirmLabel={deleting ? "deleting..." : "delete"}
        variant="danger"
        onConfirm={handleDelete}
        onCancel={() => setShowDelete(false)}
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
