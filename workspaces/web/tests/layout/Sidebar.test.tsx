import React from "react";
import { describe, it, expect, afterEach, vi, beforeEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

// Mock next/link
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    className,
  }: {
    href: string;
    children: React.ReactNode;
    className?: string;
  }) => (
    <a href={href} className={className}>
      {children}
    </a>
  ),
}));

// Mutable pathname ref so individual tests can override
let mockPathname = "/dashboards";
vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname,
}));

// Mock lucide-react icons to avoid SVG rendering issues
vi.mock("lucide-react", () => ({
  LayoutGrid: () => <span data-testid="icon-layout-grid" />,
  BarChart3: () => <span data-testid="icon-bar-chart3" />,
  Terminal: () => <span data-testid="icon-terminal" />,
  Database: () => <span data-testid="icon-database" />,
}));

// Mock next/dynamic — returns a simple stub that renders nothing for ClerkUserButton
vi.mock("next/dynamic", () => ({
  default: (_loader: unknown, _opts: unknown) => {
    const Stub = () => <div data-testid="clerk-user-button" />;
    return Stub;
  },
}));

// Mock @clerk/nextjs to avoid import errors
vi.mock("@clerk/nextjs", () => ({
  UserButton: () => <div data-testid="clerk-user-button-inner" />,
}));

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

async function importSidebar() {
  // Re-import to pick up env changes; vitest caches modules so we isolate via module reset
  const mod = await import("@/components/layout/Sidebar");
  return mod.default;
}

describe("Sidebar – navigation links", () => {
  beforeEach(() => {
    mockPathname = "/dashboards";
    vi.unstubAllEnvs();
  });

  it("renders all four nav links", async () => {
    const Sidebar = await importSidebar();
    render(<Sidebar />);

    expect(screen.getByRole("link", { name: /dashboards/i })).toBeDefined();
    expect(screen.getByRole("link", { name: /charts/i })).toBeDefined();
    expect(screen.getByRole("link", { name: /agent runs/i })).toBeDefined();
    expect(screen.getByRole("link", { name: /dbt links/i })).toBeDefined();
  });

  it("applies nav-active class to the current route link", async () => {
    mockPathname = "/charts";
    const Sidebar = await importSidebar();
    render(<Sidebar />);

    // Find the /charts link among nav links
    const links = screen.getAllByRole("link");
    const chartsLink = links.find((l) => l.getAttribute("href") === "/charts");
    expect(chartsLink).toBeDefined();
    expect(chartsLink?.className).toMatch(/nav-active/);
  });

  it("does not apply nav-active to inactive links", async () => {
    mockPathname = "/dashboards";
    const Sidebar = await importSidebar();
    render(<Sidebar />);

    const links = screen.getAllByRole("link");
    const chartsLink = links.find((l) => l.getAttribute("href") === "/charts");
    expect(chartsLink?.className).not.toMatch(/nav-active/);
  });

  it("returns null when pathname is /sign-in", async () => {
    mockPathname = "/sign-in";
    const Sidebar = await importSidebar();
    const { container } = render(<Sidebar />);
    expect(container.firstChild).toBeNull();
  });
});

describe("Sidebar – cloud UserButton", () => {
  beforeEach(() => {
    mockPathname = "/dashboards";
    vi.unstubAllEnvs();
  });

  it("does not render a clerk slot in local mode", async () => {
    vi.stubEnv("NEXT_PUBLIC_DEPLOYMENT_MODE", "local");
    // Re-require module with updated env
    const Sidebar = await importSidebar();
    render(<Sidebar />);
    // The ClerkUserButton is conditionally rendered based on isCloud const
    // In test env the dynamic stub is always returned but isCloud=false means the wrapper div isn't rendered
    expect(screen.queryByTestId("clerk-user-button")).toBeNull();
  });
});
