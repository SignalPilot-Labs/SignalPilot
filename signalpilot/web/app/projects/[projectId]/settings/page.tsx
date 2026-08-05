"use client";

import { useParams } from "next/navigation";

import { ProjectConnectionSettings } from "~/components/projects/project-connection-settings";

export default function ProjectSettingsPage() {
  const params = useParams<{ projectId: string }>();
  return <ProjectConnectionSettings projectId={params.projectId} />;
}
