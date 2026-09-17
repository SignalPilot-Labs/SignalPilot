import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Permission } from "~/lib/permissions";
import type { EvalRun } from "~/lib/api";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const mocks = vi.hoisted(() => ({
  granted: new Set<string>(),
  startBaselineEvalRun: vi.fn(),
  cancelEvalRun: vi.fn(),
}));

vi.mock("~/lib/hooks/use-permissions", () => ({
  usePermissions: () => ({
    role: mocks.granted.has("evals.run") ? "admin" : "member",
    isAdmin: mocks.granted.has("evals.run"),
    loaded: true,
    can: (p: Permission) => mocks.granted.has(p),
  }),
}));

vi.mock("~/lib/api", () => ({
  startBaselineEvalRun: () => mocks.startBaselineEvalRun(),
  cancelEvalRun: (id: string) => mocks.cancelEvalRun(id),
  getEvalRunProgress: () => Promise.resolve(undefined),
}));

vi.mock("swr", () => ({
  default: () => ({ data: undefined }),
  mutate: () => Promise.resolve(),
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

import { ControlDeck } from "~/components/evals/control-deck";

const liveRun = { id: "run-1", status: "running" } as unknown as EvalRun;

function deck(activeRun?: EvalRun, projectRepoUrl = "https://github.com/acme/dbt-project") {
  return (
    <ControlDeck
      repoUrl="https://github.com/acme/evals.git"
      projectRepoUrl={projectRepoUrl}
      model="sonnet"
      runnerEnabled
      activeRun={activeRun}
      onStarted={() => {}}
      onConfigure={() => {}}
    />
  );
}

function enabledButtons(container: HTMLElement, selector: string): HTMLButtonElement[] {
  return Array.from(container.querySelectorAll<HTMLButtonElement>(selector)).filter((b) => !b.matches(":disabled"));
}

describe("ControlDeck permissions", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    mocks.startBaselineEvalRun.mockReset();
    mocks.cancelEvalRun.mockReset();
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  it("gives a member no enabled run or stop control", async () => {
    mocks.granted = new Set(["knowledge.propose"]);
    await act(async () => root.render(deck(liveRun)));

    expect(container.querySelectorAll('[data-testid="admin-only-control"]').length).toBeGreaterThan(0);
    expect(enabledButtons(container, '[data-testid="eval-run-suite"]')).toHaveLength(0);
    expect(enabledButtons(container, '[data-testid="eval-stop-run"]')).toHaveLength(0);
    expect(enabledButtons(container, '[data-testid="eval-run-dial"]')).toHaveLength(0);
    // Configure stays open: the config panel is read-only values for a member.
    expect(enabledButtons(container, '[data-testid="eval-configure"]')).toHaveLength(1);

    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="eval-stop-run"]')!.click();
    });
    expect(mocks.cancelEvalRun).not.toHaveBeenCalled();
  });

  it("gives a member no enabled run dial when idle", async () => {
    mocks.granted = new Set();
    await act(async () => root.render(deck(undefined)));
    expect(enabledButtons(container, '[data-testid="eval-run-dial"]')).toHaveLength(0);
    expect(enabledButtons(container, '[data-testid="eval-run-suite"]')).toHaveLength(0);
  });

  it("gives an admin enabled run controls when idle and stop when live", async () => {
    mocks.granted = new Set(["evals.run"]);
    mocks.startBaselineEvalRun.mockResolvedValue({ id: "run-2" });
    await act(async () => root.render(deck(undefined)));

    expect(container.querySelector('[data-testid="admin-only-control"]')).toBeNull();
    expect(enabledButtons(container, '[data-testid="eval-run-suite"]')).toHaveLength(1);
    expect(enabledButtons(container, '[data-testid="eval-run-dial"]')).toHaveLength(1);

    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="eval-run-suite"]')!.click();
    });
    expect(mocks.startBaselineEvalRun).toHaveBeenCalledTimes(1);

    await act(async () => root.render(deck(liveRun)));
    expect(enabledButtons(container, '[data-testid="eval-stop-run"]')).toHaveLength(1);
  });

  it("blocks the run and points at configuration when no dbt project repository is set", async () => {
    mocks.granted = new Set(["evals.run"]);
    await act(async () => root.render(deck(undefined, "")));

    expect(container.querySelector('[data-testid="eval-project-blocker"]')?.textContent).toContain(
      "Select the dbt project repository.",
    );
    expect(enabledButtons(container, '[data-testid="eval-run-suite"]')).toHaveLength(0);
    expect(enabledButtons(container, '[data-testid="eval-run-dial"]')).toHaveLength(0);
  });
});
