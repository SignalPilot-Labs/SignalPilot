import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { WorkspaceList } from "@/components/dashboard/WorkspaceList";

afterEach(() => {
  cleanup();
});

describe("WorkspaceList", () => {
  it("renders one link per workspace id", () => {
    render(<WorkspaceList items={["ws-a", "ws-b", "ws-c"]} />);
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(3);
    expect(links[0].getAttribute("href")).toBe("/dashboards/ws-a");
    expect(links[1].getAttribute("href")).toBe("/dashboards/ws-b");
    expect(links[2].getAttribute("href")).toBe("/dashboards/ws-c");
    expect(links[0].textContent).toBe("ws-a");
    expect(links[1].textContent).toBe("ws-b");
    expect(links[2].textContent).toBe("ws-c");
  });

  it("renders nothing in the list body when items is empty", () => {
    render(<WorkspaceList items={[]} />);
    const list = screen.getByTestId("workspace-list");
    const links = Array.from(list.querySelectorAll("a"));
    expect(links).toHaveLength(0);
  });
});
