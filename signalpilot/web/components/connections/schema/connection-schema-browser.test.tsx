import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Permission } from "~/lib/permissions";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const mocks = vi.hoisted(() => ({
  granted: new Set<string>(),
  setSchemaEndorsements: vi.fn(async (_name: string, next: unknown) => next),
}));

vi.mock("~/lib/hooks/use-permissions", () => ({
  usePermissions: () => ({
    role: mocks.granted.has("schema.curate") ? "admin" : "member",
    isAdmin: mocks.granted.has("schema.curate"),
    loaded: true,
    can: (p: Permission) => mocks.granted.has(p),
  }),
}));

vi.mock("~/lib/connection-context", () => ({
  useConnection: () => ({ setSelectedConn: vi.fn() }),
}));

vi.mock("~/components/ui/toast", () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

vi.mock("~/lib/api", () => ({
  setSchemaEndorsements: mocks.setSchemaEndorsements,
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import { ConnectionSchemaBrowser } from "~/components/connections/schema/connection-schema-browser";

const tables = {
  "public.orders": {
    schema: "public",
    name: "orders",
    columns: [{ name: "id", type: "integer", primary_key: true }],
    foreign_keys: [],
  },
};

describe("ConnectionSchemaBrowser curation controls", () => {
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

  const render = async () => {
    await act(async () =>
      root.render(
        <ConnectionSchemaBrowser
          connectionName="warehouse"
          defaultDatabaseName="analytics"
          tables={tables}
          search=""
          searchLoading={false}
          onSearch={() => undefined}
          endorsements={{ endorsed: [], hidden: [], mode: "all" }}
          onEndorsementsChange={() => undefined}
          onReload={async () => undefined}
          onRefresh={async () => undefined}
          refreshing={false}
          schemaChanged={false}
          onGenerateSemantic={async () => undefined}
          exploringKey={null}
          exploredData={{}}
          onExplore={async () => undefined}
        />,
      ),
    );
    // The browser opens on the database picker; enter the only database.
    const dbButton = container.querySelector<HTMLButtonElement>(".connection-schema-db-grid button");
    expect(dbButton).not.toBeNull();
    await act(async () => dbButton!.click());
  };

  const endorse = () => container.querySelector<HTMLButtonElement>('[data-testid="schema-endorse-toggle"]');

  it("disables endorse, mode and semantic for a member and keeps refresh live", async () => {
    mocks.granted = new Set();
    await render();
    expect(endorse()).not.toBeNull();
    expect(endorse()!.matches(":disabled")).toBe(true);
    expect(container.querySelector('[data-testid="schema-mode-toggle"]')!.matches(":disabled")).toBe(true);
    expect(container.querySelector('[data-testid="schema-generate-semantic"]')!.matches(":disabled")).toBe(true);
    expect(container.querySelectorAll('[data-testid="admin-only-control"]').length).toBe(3);
    const refresh = container.querySelector<HTMLButtonElement>('button[title="Refresh schema metadata"]');
    expect(refresh!.matches(":disabled")).toBe(false);
    await act(async () => endorse()!.click());
    expect(mocks.setSchemaEndorsements).not.toHaveBeenCalled();
  });

  it("keeps the same controls enabled for an admin", async () => {
    mocks.granted = new Set(["schema.curate"]);
    await render();
    expect(container.querySelector('[data-testid="admin-only-control"]')).toBeNull();
    expect(endorse()!.matches(":disabled")).toBe(false);
    await act(async () => endorse()!.click());
    expect(mocks.setSchemaEndorsements).toHaveBeenCalledWith(
      "warehouse",
      expect.objectContaining({ endorsed: ["public.orders"] }),
    );
  });
});
