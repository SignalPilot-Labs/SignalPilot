import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { EvalConfig } from "~/lib/api";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const mocks = vi.hoisted(() => ({
  isCloudMode: true,
  putEvalConfig: vi.fn(),
  toast: vi.fn(),
  swrData: {} as Record<string, unknown>,
}));

vi.mock("~/lib/hooks/use-permissions", () => ({
  usePermissions: () => ({ role: "admin", isAdmin: true, loaded: true, can: () => true }),
}));

vi.mock("~/lib/auth-context", () => ({
  useAppAuth: () => ({ isCloudMode: mocks.isCloudMode, isLocalMode: !mocks.isCloudMode }),
}));

vi.mock("~/components/ui/toast", () => ({
  useToast: () => ({ toast: mocks.toast }),
}));

vi.mock("~/lib/api", () => ({
  getEvalConfig: () => Promise.resolve(undefined),
  getGitHubInstallations: () => Promise.resolve([]),
  getGitHubInstallUrl: () => Promise.resolve({ install_url: "" }),
  getGitHubRepos: () => Promise.resolve([]),
  putEvalConfig: (cfg: unknown) => mocks.putEvalConfig(cfg),
}));

vi.mock("swr", () => ({
  default: (key: string | null) => ({
    data: key ? mocks.swrData[key] : undefined,
    isLoading: false,
    error: undefined,
    mutate: () => Promise.resolve(),
  }),
  mutate: () => Promise.resolve(),
}));

import { ConfigForm } from "~/app/evals/_components/ConfigForm";

const storedConfig: EvalConfig = {
  repo_url: "https://github.com/acme/evals.git",
  repo_installation_id: "inst-1",
  repo_id: 11,
  project_repo_url: "",
  project_repo_installation_id: null,
  project_repo_id: null,
  project_ref: "",
  model: "opus",
  max_tasks: 5,
  prompt_preamble: "Use warehouse.",
  connection: "warehouse",
  autorun_on_knowledge_add: true,
  notify_emails: ["oncall@acme.com"],
};

function setControlValue(el: HTMLSelectElement | HTMLInputElement, value: string) {
  const proto = el instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(el, value);
  el.dispatchEvent(new Event(el instanceof HTMLSelectElement ? "change" : "input", { bubbles: true }));
}

describe("ConfigForm dbt project repository", () => {
  let container: HTMLDivElement;
  let root: Root;

  const q = <T extends Element>(testId: string) => container.querySelector<T>(`[data-testid="${testId}"]`);
  const set = async (testId: string, value: string) => {
    await act(async () => setControlValue(q<HTMLSelectElement>(testId)!, value));
  };
  const save = async () => {
    await act(async () => q<HTMLButtonElement>("eval-config-save")!.click());
  };

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    mocks.putEvalConfig.mockReset();
    mocks.putEvalConfig.mockResolvedValue(storedConfig);
    mocks.toast.mockReset();
    mocks.isCloudMode = true;
    mocks.swrData = {
      "eval-config": storedConfig,
      "github-installations": [{ id: "inst-1", github_account_login: "acme" }],
      "github-repos-inst-1": [{ id: 22, full_name: "acme/dbt-project", private: true, default_branch: "main" }],
    };
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  it("refuses to save without a project repository in cloud mode, then maps the picked repo into the payload", async () => {
    await act(async () => root.render(<ConfigForm onSaved={() => {}} />));

    await save();
    expect(mocks.putEvalConfig).not.toHaveBeenCalled();
    expect(mocks.toast).toHaveBeenCalledWith(expect.stringContaining("Select the dbt project repository"), "error");

    await set("project-repo-installation", "inst-1");
    await set("project-repo-repo", "22");
    await set("project-repo-ref", " release ");
    await save();

    expect(mocks.putEvalConfig).toHaveBeenCalledTimes(1);
    expect(mocks.putEvalConfig.mock.calls[0][0]).toEqual({
      repo_url: "https://github.com/acme/evals.git",
      repo_installation_id: "inst-1",
      repo_id: 11,
      project_repo_url: "https://github.com/acme/dbt-project",
      project_repo_installation_id: "inst-1",
      project_repo_id: 22,
      project_ref: "release",
      model: "opus",
      max_tasks: 5,
      prompt_preamble: "Use warehouse.",
      connection: "warehouse",
      autorun_on_knowledge_add: true,
      notify_emails: ["oncall@acme.com"],
    });
  });

  it("shows the GitHub-only eval repo placeholder in cloud mode and clears the pairing when the URL is typed", async () => {
    await act(async () => root.render(<ConfigForm onSaved={() => {}} />));
    const evalRepo = q<HTMLInputElement>("eval-repo-url")!;
    expect(evalRepo.placeholder).toBe("https://github.com/org/eval-set");
    expect(q("project-repo-url")).toBeNull();

    await set("project-repo-installation", "inst-1");
    await set("project-repo-repo", "22");
    await act(async () => setControlValue(evalRepo, "https://github.com/acme/other-evals"));
    await save();

    expect(mocks.putEvalConfig.mock.calls[0][0]).toMatchObject({
      repo_url: "https://github.com/acme/other-evals",
      repo_installation_id: null,
      repo_id: null,
    });
  });

  it("keeps the local-path hint and accepts a typed project path in self-host mode", async () => {
    mocks.isCloudMode = false;
    await act(async () => root.render(<ConfigForm onSaved={() => {}} />));
    expect(q<HTMLInputElement>("eval-repo-url")!.placeholder).toContain("/eval-projects/northwind");

    await set("project-repo-url", "/eval-projects/northwind");
    await save();

    expect(mocks.putEvalConfig.mock.calls[0][0]).toMatchObject({
      project_repo_url: "/eval-projects/northwind",
      project_repo_installation_id: null,
      project_repo_id: null,
      project_ref: "",
    });
  });
});
