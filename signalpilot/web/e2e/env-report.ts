/**
 * Pre-test environment report. Run before the suite to know
 * exactly what projects, files, and sessions exist.
 * Import and call `printEnvReport()` at the top of any test.
 */

const GATEWAY = "http://localhost:3300";
const WEB = "http://localhost:3200";

interface Project {
  id: string;
  name: string;
  display_name: string;
  status: string;
  file_count: number;
  default_branch: string | null;
  description: string;
}

interface FileEntry {
  key?: string;
  name?: string;
  path?: string;
  size?: number;
}

interface Session {
  id: string;
  project_id: string;
  branch: string;
  status: string;
  pod_name: string;
  notebook_url: string;
}

export interface EnvReport {
  apiKey: string;
  projects: (Project & { files: string[] })[];
  session: Session | null;
}

export async function getEnvReport(): Promise<EnvReport> {
  // Get API key
  const keyResp = await fetch(`${WEB}/api/local-key`);
  const keyData = (await keyResp.json()) as { key?: string };
  const apiKey = keyData?.key ?? "";
  const headers = { Authorization: `Bearer ${apiKey}` };

  // Get projects
  const projResp = await fetch(`${GATEWAY}/api/workspace-projects?status=active&limit=50`, { headers });
  const projData = (await projResp.json()) as { projects?: Project[] };
  const projects = projData?.projects ?? [];

  // Get files for each project
  const projectsWithFiles: (Project & { files: string[] })[] = [];
  for (const p of projects) {
    const branch = p.default_branch || "main";
    let files: string[] = [];
    try {
      const filesResp = await fetch(
        `${GATEWAY}/api/workspace-projects/${p.id}/branches/${branch}/files`,
        { headers },
      );
      if (filesResp.ok) {
        const filesData = (await filesResp.json()) as { files?: FileEntry[]; entries?: FileEntry[] };
        const entries = filesData?.files ?? filesData?.entries ?? [];
        files = entries.map((f) => f.key ?? f.name ?? f.path ?? "?");
      }
    } catch {}
    projectsWithFiles.push({ ...p, files });
  }

  // Get session
  let session: Session | null = null;
  try {
    const sessResp = await fetch(`${GATEWAY}/api/notebook-sessions`, { headers });
    if (sessResp.ok) {
      const sessData = (await sessResp.json()) as Session;
      if (sessData?.id) session = sessData;
    }
  } catch {}

  return { apiKey, projects: projectsWithFiles, session };
}

export function printEnvReport(report: EnvReport) {
  console.log("\n╔══════════════════════════════════════════════════╗");
  console.log("║           PRE-TEST ENVIRONMENT REPORT            ║");
  console.log("╠══════════════════════════════════════════════════╣");

  console.log(`║ API Key: ${report.apiKey.slice(0, 20)}...`);
  console.log(`║ Projects: ${report.projects.length}`);
  console.log(`║ Active Session: ${report.session ? `${report.session.id.slice(0, 12)}... (${report.session.status})` : "none"}`);

  if (report.session) {
    console.log(`║   Project: ${report.session.project_id.slice(0, 12)}...`);
    console.log(`║   Branch:  ${report.session.branch}`);
    console.log(`║   Pod:     ${report.session.pod_name}`);
  }

  console.log("╠══════════════════════════════════════════════════╣");

  for (const p of report.projects) {
    console.log(`║ 📁 ${p.name} (${p.id.slice(0, 8)}...)`);
    console.log(`║    Status: ${p.status}  Files: ${p.files.length}  Branch: ${p.default_branch ?? "main"}`);
    if (p.files.length > 0) {
      for (const f of p.files.slice(0, 15)) {
        console.log(`║      ${f}`);
      }
      if (p.files.length > 15) {
        console.log(`║      ... +${p.files.length - 15} more`);
      }
    } else {
      console.log("║      (no files)");
    }
  }

  console.log("╚══════════════════════════════════════════════════╝\n");
}
