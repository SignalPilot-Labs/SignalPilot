import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Permission } from "~/lib/permissions";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const mocks = vi.hoisted(() => ({
  granted: new Set<string>(),
}));

vi.mock("~/lib/hooks/use-permissions", () => ({
  usePermissions: () => ({
    role: mocks.granted.has("connections.write") ? "admin" : "member",
    isAdmin: mocks.granted.has("connections.write"),
    loaded: true,
    can: (p: Permission) => mocks.granted.has(p),
  }),
}));

// The local-file picker (sqlite/duckdb) reaches the gateway; nothing here does.
vi.mock("~/lib/api", () => ({
  browseFiles: vi.fn(async () => ({ entries: [] })),
}));

import { ConnectionEditor } from "~/components/connections/editor/connection-editor";
import { REDACTED_VALUE } from "~/components/connections/editor/connection-read-only-view";
import type { ConnectionsController } from "~/components/connections/hooks/use-connections-controller";
import { DB_CONFIGS } from "~/lib/connections/connector-catalog";
import { DEFAULT_CONNECTION_FORM } from "~/lib/connections/defaults";

function makeController(overrides: Partial<ConnectionsController> = {}): ConnectionsController {
  const form = {
    ...DEFAULT_CONNECTION_FORM,
    name: "prod-analytics",
    db_type: "postgres" as const,
    connectionMode: "fields" as const,
    host: "db.internal.example",
    port: "5432",
    database: "analytics",
    username: "reader",
    password: "",
    description: "Production analytics DB",
    tags: ["prod"],
    ssl_enabled: true,
    ssl_mode: "require",
  };
  const controller = {
    toast: vi.fn(),
    showForm: true,
    setShowForm: vi.fn(),
    editingConnection: "prod-analytics",
    setEditingConnection: vi.fn(),
    form,
    setForm: vi.fn(),
    selectedVariant: "default",
    showAdvanced: false,
    setShowAdvanced: vi.fn(),
    advancedTab: "security",
    setAdvancedTab: vi.fn(),
    serverIp: null,
    preTesting: false,
    preTestResult: null,
    setPreTestResult: vi.fn(),
    saving: false,
    formErrors: {},
    hasFormErrors: false,
    fieldRefs: { current: {} },
    serverFieldErrors: {},
    setServerFieldErrors: vi.fn(),
    handleDbTypeChange: vi.fn(),
    handleVariantChange: vi.fn(),
    handlePreTest: vi.fn(),
    handleCreate: vi.fn(),
    handleSaveAndTest: vi.fn(),
    config: DB_CONFIGS.postgres,
    ...overrides,
  };
  return controller as unknown as ConnectionsController;
}

function buttonLabels(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll("button")).map((b) => (b.textContent ?? "").trim().toLowerCase());
}

describe("ConnectionEditor member treatment", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  it("renders a saved connection as values, with no inputs or write actions, for a member", async () => {
    mocks.granted = new Set();
    await act(async () => root.render(<ConnectionEditor controller={makeController()} />));

    expect(container.querySelector('[data-testid="connection-read-only-view"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="read-only-note"]')).not.toBeNull();
    expect(container.textContent).toContain("Managed by your org admins");

    // Values, not inputs.
    expect(container.querySelectorAll("input, select, textarea").length).toBe(0);
    expect(container.textContent).toContain("prod-analytics");
    expect(container.textContent).toContain("PostgreSQL");
    expect(container.textContent).toContain("db.internal.example");
    expect(container.textContent).toContain("5432");
    expect(container.textContent).toContain("analytics");
    expect(container.textContent).toContain("reader");
    expect(container.textContent).toContain("prod");

    // Credentials are redacted, never echoed.
    expect(container.textContent).toContain(REDACTED_VALUE);

    // No save / update / test-credentials / delete affordances.
    const labels = buttonLabels(container);
    expect(labels).toEqual(["close"]);
    expect(labels.some((l) => /save|update|test|delete/.test(l))).toBe(false);
  });

  it("closes the read-only view without touching the connection", async () => {
    mocks.granted = new Set();
    const controller = makeController();
    await act(async () => root.render(<ConnectionEditor controller={controller} />));
    const close = Array.from(container.querySelectorAll("button")).find((b) => b.textContent?.includes("close"));
    expect(close).toBeDefined();
    await act(async () => close!.click());
    expect(controller.setShowForm).toHaveBeenCalledWith(false);
    expect(controller.setEditingConnection).toHaveBeenCalledWith(null);
    expect(controller.handleCreate).not.toHaveBeenCalled();
    expect(controller.handlePreTest).not.toHaveBeenCalled();
  });

  it("renders nothing for a member when the form is open with no saved connection", async () => {
    mocks.granted = new Set();
    await act(async () =>
      root.render(<ConnectionEditor controller={makeController({ editingConnection: null })} />),
    );
    expect(container.innerHTML).toBe("");
  });

  it("renders the full editor with inputs and write actions for an admin", async () => {
    mocks.granted = new Set(["connections.write", "connections.test_credentials"]);
    await act(async () => root.render(<ConnectionEditor controller={makeController()} />));

    expect(container.querySelector('[data-testid="connection-read-only-view"]')).toBeNull();
    expect(container.querySelector('[data-testid="read-only-note"]')).toBeNull();
    expect(container.querySelectorAll("input").length).toBeGreaterThan(0);

    const labels = buttonLabels(container);
    expect(labels).toContain("update connection");
    expect(labels).toContain("test connection");
    expect(labels).toContain("update & test");
    expect(labels).toContain("cancel");
  });
});
