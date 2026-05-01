import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { TopNav } from "@/components/nav/TopNav";

afterEach(() => {
  cleanup();
});

describe("TopNav", () => {
  it("renders product name and dashboards link", () => {
    render(<TopNav />);
    const links = screen.getAllByRole("link");
    const hrefs = links.map((l) => l.getAttribute("href"));
    expect(hrefs).toContain("/");
    expect(hrefs).toContain("/dashboards");
    expect(screen.getByText("Workspaces")).toBeDefined();
    expect(screen.getByText("Dashboards")).toBeDefined();
  });

  it("renders New chart link pointing to /charts/new", () => {
    render(<TopNav />);
    const links = screen.getAllByRole("link");
    const hrefs = links.map((l) => l.getAttribute("href"));
    expect(hrefs).toContain("/charts/new");
    expect(screen.getByText("New chart")).toBeDefined();
  });

  it("renders Charts link pointing to /charts", () => {
    render(<TopNav />);
    const links = screen.getAllByRole("link");
    const hrefs = links.map((l) => l.getAttribute("href"));
    expect(hrefs).toContain("/charts");
    expect(screen.getByText("Charts")).toBeDefined();
  });
});
