import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectConnectionSettings } from "~/components/projects/project-connection-settings";
import type { ConnectionInfo, WorkspaceProjectInfo } from "~/lib/types";

const mocks = vi.hoisted(() => ({
  getConnections: vi.fn(),
  getReadiness: vi.fn(),
  getProject: vi.fn(),
  testConnection: vi.fn(),
  updateProject: vi.fn(),
  toast: vi.fn(),
  push: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push }),
  usePathname: () => "/projects/project-1/settings",
}));

vi.mock("~/components/ui/toast", () => ({
  useToast: () => ({ toast: mocks.toast }),
}));

vi.mock("~/lib/api", () => ({
  getConnections: mocks.getConnections,
  getStandaloneChatProjectReadiness: mocks.getReadiness,
  getWorkspaceProject: mocks.getProject,
  testConnection: mocks.testConnection,
  updateWorkspaceProject: mocks.updateProject,
}));

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const project: WorkspaceProjectInfo = {
  id: "project-1",
  org_id: "org-1",
  name: "revenue",
  display_name: "Revenue",
  description: null,
  source: "managed",
  connection_name: null,
  status: "active",
  tags: [],
  settings: null,
  file_count: 2,
  total_bytes: 100,
  default_branch: "main",
  created_by: "user-1",
  created_at: 1,
  updated_at: 1,
};

const connection = {
  id: "connection-1",
  name: "warehouse",
  db_type: "postgres",
} as ConnectionInfo;

const unready = {
  project_id: project.id,
  ready: false,
  code: "connection_missing",
  message: "A production data connection has not been configured.",
  setup_cta: true,
  branch: "main",
  connection_name: null,
  starter_questions: [],
};

async function settle() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("ProjectConnectionSettings", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(async () => {
    vi.clearAllMocks();
    mocks.getProject.mockResolvedValue(project);
    mocks.getConnections.mockResolvedValue([connection]);
    mocks.getReadiness.mockResolvedValue(unready);

    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root.render(<ProjectConnectionSettings projectId={project.id} />);
    });
    await settle();
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  it("does not assign a connection that fails validation", async () => {
    mocks.testConnection.mockResolvedValue({
      status: "unhealthy",
      message: "Credentials were rejected",
    });

    const select = container.querySelector("select")!;
    const setter = Object.getOwnPropertyDescriptor(
      HTMLSelectElement.prototype,
      "value",
    )?.set;
    await act(async () => {
      setter?.call(select, connection.name);
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    const save = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.includes("Validate and save"),
    )!;
    await act(async () => save.click());
    await settle();

    expect(mocks.testConnection).toHaveBeenCalledWith(connection.name);
    expect(mocks.updateProject).not.toHaveBeenCalled();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "Credentials were rejected",
    );
  });

  it("assigns a healthy connection with PUT and refreshes readiness", async () => {
    const updated = { ...project, connection_name: connection.name };
    mocks.testConnection.mockResolvedValue({
      status: "healthy",
      message: "Connection healthy",
    });
    mocks.updateProject.mockResolvedValue(updated);
    mocks.getReadiness.mockResolvedValue({
      ...unready,
      ready: true,
      code: "ready",
      message: "Ready",
      connection_name: connection.name,
    });

    const select = container.querySelector("select")!;
    const setter = Object.getOwnPropertyDescriptor(
      HTMLSelectElement.prototype,
      "value",
    )?.set;
    await act(async () => {
      setter?.call(select, connection.name);
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    const save = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.includes("Validate and save"),
    )!;
    await act(async () => save.click());
    await settle();

    expect(mocks.updateProject).toHaveBeenCalledWith(project.id, {
      connection_name: connection.name,
    });
    expect(mocks.getReadiness).toHaveBeenCalledTimes(2);
    expect(container.textContent).toContain("Ready");
    expect(mocks.toast).toHaveBeenCalledWith(
      "Production connection assigned",
      "success",
    );
  });
});
