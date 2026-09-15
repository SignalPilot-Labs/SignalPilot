import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Permission } from "~/lib/permissions";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const mocks = vi.hoisted(() => ({
  granted: new Set<string>(),
  createKnowledgeDoc: vi.fn(),
  toast: vi.fn(),
}));

vi.mock("~/lib/hooks/use-permissions", () => ({
  usePermissions: () => ({
    role: mocks.granted.has("knowledge.publish") ? "admin" : "member",
    isAdmin: mocks.granted.has("knowledge.publish"),
    loaded: true,
    can: (p: Permission) => mocks.granted.has(p),
  }),
}));

vi.mock("~/lib/api", () => ({
  createKnowledgeDoc: (payload: unknown) => mocks.createKnowledgeDoc(payload),
  getProjects: () => Promise.resolve([]),
  getConnections: () => Promise.resolve([]),
}));

vi.mock("~/components/ui/toast", () => ({
  useToast: () => ({ toast: mocks.toast }),
}));

import { CreateDocForm, PROPOSE_ACTION_LABEL, CREATE_ACTION_LABEL } from "~/components/knowledge/create-doc-form";

function setValue(el: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")!.set!;
  setter.call(el, value);
  el.dispatchEvent(new Event("input", { bubbles: true }));
}

describe("CreateDocForm", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    mocks.createKnowledgeDoc.mockReset();
    mocks.toast.mockReset();
    mocks.createKnowledgeDoc.mockResolvedValue({ id: "doc-1", status: "pending" });
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  async function fillAndSubmit() {
    const title = container.querySelector<HTMLInputElement>('input[placeholder="e.g. postgres-naming-conventions"]')!;
    const body = container.querySelector<HTMLTextAreaElement>("textarea")!;
    await act(async () => {
      setValue(title, "naming-rules");
      setValue(body, "use snake_case");
    });
    await act(async () => {
      container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
  }

  it("labels the action 'Propose an entry' and sends status pending for a member", async () => {
    mocks.granted = new Set(["knowledge.propose"]);
    const onCreated = vi.fn();
    await act(async () => root.render(<CreateDocForm onCancel={() => {}} onCreated={onCreated} />));

    const submit = container.querySelector<HTMLButtonElement>('[data-testid="create-doc-submit"]')!;
    expect(submit.textContent).toContain(PROPOSE_ACTION_LABEL);
    expect(container.textContent).not.toContain(CREATE_ACTION_LABEL);
    expect(container.querySelector('[data-testid="propose-note"]')).not.toBeNull();

    await fillAndSubmit();
    expect(mocks.createKnowledgeDoc).toHaveBeenCalledTimes(1);
    expect(mocks.createKnowledgeDoc.mock.calls[0][0]).toMatchObject({
      title: "naming-rules",
      body: "use snake_case",
      status: "pending",
    });
    expect(onCreated).toHaveBeenCalledWith({ id: "doc-1", status: "pending" });
  });

  it("keeps the admin create flow without a pending marker", async () => {
    mocks.granted = new Set(["knowledge.publish", "knowledge.propose"]);
    await act(async () => root.render(<CreateDocForm onCancel={() => {}} onCreated={() => {}} />));

    const submit = container.querySelector<HTMLButtonElement>('[data-testid="create-doc-submit"]')!;
    expect(submit.textContent).toContain(CREATE_ACTION_LABEL);
    expect(container.querySelector('[data-testid="propose-note"]')).toBeNull();

    await fillAndSubmit();
    expect(mocks.createKnowledgeDoc).toHaveBeenCalledTimes(1);
    const payload = mocks.createKnowledgeDoc.mock.calls[0][0] as Record<string, unknown>;
    expect(payload.title).toBe("naming-rules");
    expect("status" in payload).toBe(false);
  });
});
