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

  it("renders Agent runs and New agent run links between dbt-links and charts groups", () => {
    render(<TopNav />);
    const links = screen.getAllByRole("link");
    const hrefs = links.map((l) => l.getAttribute("href"));

    expect(hrefs).toContain("/agent-runs");
    expect(hrefs).toContain("/agent-runs/new");
    expect(screen.getByText("Agent runs")).toBeDefined();
    expect(screen.getByText("New agent run")).toBeDefined();

    // Verify order: dbt-links → New dbt link → Agent runs → New agent run → New chart
    const newDbtLinkIdx = hrefs.indexOf("/dbt-links/new");
    const agentRunsIdx = hrefs.indexOf("/agent-runs");
    const newAgentRunIdx = hrefs.indexOf("/agent-runs/new");
    const newChartIdx = hrefs.indexOf("/charts/new");

    expect(newDbtLinkIdx).toBeLessThan(agentRunsIdx);
    expect(agentRunsIdx).toBeLessThan(newAgentRunIdx);
    expect(newAgentRunIdx).toBeLessThan(newChartIdx);
  });

  it("renders 8 links total in correct order", () => {
    render(<TopNav />);
    const links = screen.getAllByRole("link");
    const hrefs = links.map((l) => l.getAttribute("href"));

    expect(hrefs).toEqual([
      "/",
      "/dashboards",
      "/charts",
      "/dbt-links",
      "/dbt-links/new",
      "/agent-runs",
      "/agent-runs/new",
      "/charts/new",
    ]);
  });
});
