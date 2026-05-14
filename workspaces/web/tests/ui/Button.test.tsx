import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { Button, LinkButton } from "@/components/ui/Button";

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

afterEach(() => {
  cleanup();
});

describe("Button", () => {
  it("renders children as button text", () => {
    render(<Button>Click me</Button>);
    expect(screen.getByRole("button", { name: "Click me" })).toBeDefined();
  });

  it("is disabled and aria-busy when pending=true", () => {
    render(
      <Button pending pendingLabel="Saving…">
        Save
      </Button>
    );
    const btn = screen.getByRole("button");
    expect(btn.getAttribute("disabled")).not.toBeNull();
    expect(btn.getAttribute("aria-busy")).toBe("true");
    expect(btn.textContent).toBe("Saving…");
  });

  it("shows children when pending but no pendingLabel", () => {
    render(<Button pending>Save</Button>);
    const btn = screen.getByRole("button");
    expect(btn.textContent).toBe("Save");
    expect(btn.getAttribute("disabled")).not.toBeNull();
  });

  it("calls onClick when clicked", () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Go</Button>);
    fireEvent.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("does not call onClick when disabled", () => {
    const onClick = vi.fn();
    render(
      <Button disabled onClick={onClick}>
        Go
      </Button>
    );
    // disabled button does not fire click handler
    fireEvent.click(screen.getByRole("button"));
    expect(onClick).not.toHaveBeenCalled();
  });

  it("applies danger variant class referencing color-error", () => {
    render(<Button variant="danger">Delete</Button>);
    const btn = screen.getByRole("button");
    expect(btn.className).toMatch(/color-error/);
  });

  it("applies type=submit when specified", () => {
    render(<Button type="submit">Submit</Button>);
    expect(screen.getByRole("button").getAttribute("type")).toBe("submit");
  });

  it("defaults to type=button", () => {
    render(<Button>Click</Button>);
    expect(screen.getByRole("button").getAttribute("type")).toBe("button");
  });
});

describe("LinkButton", () => {
  it("renders as an anchor with correct href", () => {
    render(<LinkButton href="/charts">View Charts</LinkButton>);
    const link = screen.getByRole("link", { name: "View Charts" });
    expect(link.getAttribute("href")).toBe("/charts");
  });

  it("applies secondary variant class (underline style, no border)", () => {
    render(
      <LinkButton href="/charts" variant="secondary">
        Charts
      </LinkButton>
    );
    const link = screen.getByRole("link");
    // SECONDARY_BTN_CLASS uses underline text-dim style — no box border
    expect(link.className).toMatch(/underline/);
    expect(link.className).toMatch(/color-text-dim/);
  });

  it("applies primary variant class referencing color-text", () => {
    render(<LinkButton href="/dashboards">Home</LinkButton>);
    const link = screen.getByRole("link");
    expect(link.className).toMatch(/color-text/);
  });
});
