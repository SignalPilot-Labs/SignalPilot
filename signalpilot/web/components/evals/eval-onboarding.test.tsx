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
  swrData: {} as Record<string, unknown>,
}));

vi.mock("~/lib/hooks/use-permissions", () => ({
  usePermissions: () => ({ role: "admin", isAdmin: true, loaded: true, can: () => true }),
}));

vi.mock("~/lib/auth-context", () => ({
  useAppAuth: () => ({ isCloudMode: mocks.isCloudMode, isLocalMode: !mocks.isCloudMode }),
}));

vi.mock("~/components/ui/toast", () => ({
  useToast: () => ({ toast: () => {} }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

vi.mock("~/lib/api", () => ({
  getConnections: () => Promise.resolve([]),
  getGitHubInstallations: () => Promise.resolve([]),
  getGitHubInstallUrl: () => Promise.resolve({ install_url: "" }),
  getGitHubRepos: () => Promise.resolve([]),
  getEvalConfig: () => Promise.resolve(undefined),
  putEvalConfig: (cfg: unknown) => mocks.putEvalConfig(cfg),
}));

// SWR is replaced by a synchronous lookup so each key resolves on first render.
vi.mock("swr", () => ({
  default: (key: string | null) => ({
    data: key ? mocks.swrData[key] : undefined,
    isLoading: false,
    error: undefined,
    mutate: () => Promise.resolve(),
  }),
  mutate: () => Promise.resolve(),
}));

import { EvalOnboarding } from "~/app/evals/_components/EvalOnboarding";

const emptyConfig: EvalConfig = {
  repo_url: "",
  repo_installation_id: null,
  repo_id: null,
  project_repo_url: "",
  project_repo_installation_id: null,
  project_repo_id: null,
  project_ref: "",
  model: "sonnet",
  max_tasks: 0,
  prompt_preamble: "",
  connection: "",
  autorun_on_knowledge_add: false,
  notify_emails: [],
};

function seedSwr() {
  mocks.swrData = {
    connections: [{ id: "c1", name: "warehouse", db_type: "postgres" }],
    "github-installations": [{ id: "inst-1", github_account_login: "acme" }],
    "github-repos-inst-1": [
      { id: 11, full_name: "acme/evals", private: true, default_branch: "main" },
      { id: 22, full_name: "acme/dbt-project", private: true, default_branch: "main" },
    ],
  };
}

function setControlValue(el: HTMLSelectElement | HTMLInputElement, value: string) {
  const proto = el instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(el, value);
  el.dispatchEvent(new Event(el instanceof HTMLSelectElement ? "change" : "input", { bubbles: true }));
}

describe("EvalOnboarding dbt project step", () => {
  let container: HTMLDivElement;
  let root: Root;

  const q = <T extends Element>(testId: string) => container.querySelector<T>(`[data-testid="${testId}"]`);
  const set = async (testId: string, value: string) => {
    await act(async () => setControlValue(q<HTMLSelectElement>(testId)!, value));
  };
  const click = async (testId: string) => {
    await act(async () => q<HTMLButtonElement>(testId)!.click());
  };
  const alertText = () => container.querySelector('[role="alert"]')?.textContent ?? "";

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    mocks.putEvalConfig.mockReset();
    mocks.putEvalConfig.mockResolvedValue(emptyConfig);
    mocks.isCloudMode = true;
    seedSwr();
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  it("requires a picked project repository in cloud mode and sends the four project fields", async () => {
    await act(async () => root.render(<EvalOnboarding config={emptyConfig} onComplete={() => {}} />));

    await click("source-kind-private");
    await set("eval-repo-installation", "inst-1");
    await set("eval-repo-repo", "11");
    await click("onboarding-continue");
    expect(q("onboarding-step-project")).not.toBeNull();

    // Continue without a selection stays on the step with the blocker message.
    await click("onboarding-continue");
    expect(q("onboarding-step-project")).not.toBeNull();
    expect(alertText()).toContain("Select the dbt project repository");

    await set("project-repo-installation", "inst-1");
    await set("project-repo-repo", "22");
    await set("project-repo-ref", " main ");
    await click("onboarding-continue");
    expect(q("eval-connection")).not.toBeNull();

    await set("eval-connection", "warehouse");
    await click("onboarding-continue");
    await click("onboarding-finish");

    expect(mocks.putEvalConfig).toHaveBeenCalledTimes(1);
    expect(mocks.putEvalConfig.mock.calls[0][0]).toMatchObject({
      repo_url: "https://github.com/acme/evals.git",
      repo_installation_id: "inst-1",
      repo_id: 11,
      project_repo_url: "https://github.com/acme/dbt-project",
      project_repo_installation_id: "inst-1",
      project_repo_id: 22,
      project_ref: "main",
      connection: "warehouse",
    });
  });

  it("accepts a local path for the project in self-host mode with no installation pairing", async () => {
    mocks.isCloudMode = false;
    await act(async () => root.render(<EvalOnboarding config={emptyConfig} onComplete={() => {}} />));

    const sourceInput = container.querySelector<HTMLInputElement>('[data-testid="onboarding-step-source"] input')!;
    await act(async () => setControlValue(sourceInput, "https://github.com/acme/evals.git"));
    await click("onboarding-continue");

    await click("onboarding-continue");
    expect(alertText()).toContain("Enter the dbt project repository");

    await set("project-repo-url", "/eval-projects/northwind");
    await click("onboarding-continue");
    await set("eval-connection", "warehouse");
    await click("onboarding-continue");
    await click("onboarding-finish");

    expect(mocks.putEvalConfig.mock.calls[0][0]).toMatchObject({
      repo_url: "https://github.com/acme/evals.git",
      repo_installation_id: null,
      repo_id: null,
      project_repo_url: "/eval-projects/northwind",
      project_repo_installation_id: null,
      project_repo_id: null,
      project_ref: "",
    });
  });
});
