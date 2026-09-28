import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { TableauIntegrationInfo } from "~/lib/api";

// The card lives beside the /integrations page (app/ is outside the vitest
// include globs), so its test sits with the other integration components.

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  save: vi.fn(),
  patch: vi.fn(),
  test: vi.fn(),
  del: vi.fn(),
}));

vi.mock("~/components/ui/toast", () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

vi.mock("~/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("~/lib/api")>();
  return {
    ...actual,
    getTableauIntegration: mocks.get,
    saveTableauIntegration: mocks.save,
    setTableauIntegrationEnabled: mocks.patch,
    testTableauIntegration: mocks.test,
    deleteTableauIntegration: mocks.del,
  };
});

import { ApiRequestError } from "~/lib/api";
import { TableauIntegrationSection } from "~/app/integrations/_components/tableau-integration-section";

const UNCONFIGURED: TableauIntegrationInfo = {
  configured: false,
  enabled: false,
  active: false,
  server_url: null,
  site_content_url: null,
  site_url: null,
  pat_name: null,
  status: null,
  last_error: null,
  user_name: null,
  site_role: null,
  verified_at: null,
  updated_at: null,
};

const CONFIGURED: TableauIntegrationInfo = {
  configured: true,
  enabled: true,
  active: true,
  server_url: "https://10ay.online.tableau.com",
  site_content_url: "acme",
  site_url: "https://10ay.online.tableau.com/#/site/acme",
  pat_name: "sp-token",
  status: "ok",
  last_error: null,
  user_name: "daniel@acme.com",
  site_role: "SiteAdministratorCreator",
  verified_at: Date.now() / 1000 - 120,
  updated_at: Date.now() / 1000 - 120,
};

function setInput(container: HTMLElement, id: string, value: string) {
  const input = container.querySelector<HTMLInputElement>(`#${id}`);
  if (!input) throw new Error(`input ${id} not found`);
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  setter?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

function buttonByText(container: HTMLElement, text: string): HTMLButtonElement {
  const button = Array.from(container.querySelectorAll("button")).find(
    (b) => b.textContent?.trim() === text,
  );
  if (!button) throw new Error(`button "${text}" not found`);
  return button;
}

describe("TableauIntegrationSection", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    Object.values(mocks).forEach((m) => m.mockReset());
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (readOnly = false) => {
    await act(async () => {
      root.render(<TableauIntegrationSection readOnly={readOnly} />);
    });
  };

  it("renders the empty form with the #tableau anchor when unconfigured", async () => {
    mocks.get.mockResolvedValue(UNCONFIGURED);
    await render();

    expect(container.querySelector("section#tableau")).not.toBeNull();
    const site = container.querySelector<HTMLInputElement>("#tableau-site-url");
    expect(site?.placeholder).toBe("https://10ay.online.tableau.com/#/site/your-site");
    expect(container.textContent).toContain("Paste any URL from your Tableau site.");
    expect(container.querySelector<HTMLInputElement>("#tableau-pat-secret")?.type).toBe("password");
    expect(container.textContent).not.toContain("Saved. Leave blank to keep it.");
    expect(container.textContent).toContain("Chat agents can find, build, and edit workbooks");
    expect(container.querySelector("[data-testid=tableau-enabled-switch]")).toBeNull();
    // Nothing typed yet: the secret is required on the first save.
    expect(buttonByText(container, "Save and test").disabled).toBe(true);
  });

  it("PUTs the site URL, token name, and secret on Save and test", async () => {
    mocks.get.mockResolvedValue(UNCONFIGURED);
    mocks.save.mockResolvedValue(CONFIGURED);
    await render();

    await act(async () => {
      setInput(container, "tableau-site-url", " https://10ay.online.tableau.com/#/site/acme/home ");
      setInput(container, "tableau-pat-name", "sp-token");
      setInput(container, "tableau-pat-secret", "s3cret");
    });
    await act(async () => buttonByText(container, "Save and test").click());

    expect(mocks.save).toHaveBeenCalledWith({
      site_url: "https://10ay.online.tableau.com/#/site/acme/home",
      pat_name: "sp-token",
      pat_secret: "s3cret",
    });
    expect(container.querySelector("[data-testid=tableau-status]")?.textContent).toContain(
      "Connected as daniel@acme.com (SiteAdministratorCreator)",
    );
  });

  it("shows the gateway detail inline when the save is rejected", async () => {
    mocks.get.mockResolvedValue(UNCONFIGURED);
    mocks.save.mockRejectedValue(
      new ApiRequestError(400, JSON.stringify({ detail: "Signin failed: invalid PAT (401001)" })),
    );
    await render();

    await act(async () => {
      setInput(container, "tableau-site-url", "https://10ay.online.tableau.com/#/site/acme");
      setInput(container, "tableau-pat-name", "sp-token");
      setInput(container, "tableau-pat-secret", "wrong");
    });
    await act(async () => buttonByText(container, "Save and test").click());

    expect(container.querySelector("[data-testid=tableau-error]")?.textContent).toBe(
      "Signin failed: invalid PAT (401001)",
    );
  });

  it("shows status, the enabled switch, and keeps the secret when configured", async () => {
    mocks.get.mockResolvedValue(CONFIGURED);
    mocks.patch.mockResolvedValue({ ...CONFIGURED, enabled: false, active: false });
    mocks.save.mockResolvedValue(CONFIGURED);
    await render();

    const status = container.querySelector("[data-testid=tableau-status]");
    expect(status?.textContent).toContain("Connected as daniel@acme.com (SiteAdministratorCreator)");
    expect(status?.textContent).toMatch(/verified 2m ago/);
    expect(container.textContent).toContain("Saved. Leave blank to keep it.");
    expect(container.querySelector<HTMLInputElement>("#tableau-site-url")?.value).toBe(CONFIGURED.site_url);

    const toggle = container.querySelector<HTMLButtonElement>("[data-testid=tableau-enabled-switch]");
    expect(toggle?.getAttribute("aria-checked")).toBe("true");
    await act(async () => toggle?.click());
    expect(mocks.patch).toHaveBeenCalledWith(false);
    expect(toggle?.getAttribute("aria-checked")).toBe("false");

    // A blank secret on re-save omits pat_secret so the stored one is kept.
    await act(async () => buttonByText(container, "Save and test").click());
    expect(mocks.save).toHaveBeenCalledWith({ site_url: CONFIGURED.site_url, pat_name: "sp-token" });
  });

  it("shows the stored error in red", async () => {
    mocks.get.mockResolvedValue({ ...CONFIGURED, active: false, status: "error", last_error: "PAT expired" });
    await render();
    expect(container.querySelector("[data-testid=tableau-status]")?.textContent).toContain("PAT expired");
  });

  it("confirms before Disconnect and DELETEs", async () => {
    mocks.get.mockResolvedValueOnce(CONFIGURED).mockResolvedValueOnce(UNCONFIGURED);
    mocks.del.mockResolvedValue(undefined);
    await render();

    await act(async () => buttonByText(container, "Disconnect").click());
    expect(mocks.del).not.toHaveBeenCalled();
    const dialog = container.querySelector("[data-testid=confirm-dialog]");
    expect(dialog).not.toBeNull();
    await act(async () => buttonByText(container, "disconnect").click());
    expect(mocks.del).toHaveBeenCalledTimes(1);
    expect(container.querySelector("[data-testid=tableau-enabled-switch]")).toBeNull();
  });

  it("gives members a read-only status and no form", async () => {
    mocks.get.mockResolvedValue(CONFIGURED);
    await render(true);

    expect(container.querySelector("[data-testid=tableau-form]")).toBeNull();
    expect(container.querySelector("[data-testid=read-only-note]")).not.toBeNull();
    expect(container.textContent).not.toContain("Disconnect");
    expect(container.textContent).not.toContain("Test again");
    const toggle = container.querySelector<HTMLButtonElement>("[data-testid=tableau-enabled-switch]");
    expect(toggle?.disabled).toBe(true);
  });
});
