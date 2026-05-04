import React from "react";
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { StatusPill, statusToneFor } from "@/components/ui/StatusPill";

afterEach(() => {
  cleanup();
});

describe("StatusPill", () => {
  it("renders children text", () => {
    render(<StatusPill tone="success">Succeeded</StatusPill>);
    expect(screen.getByText("Succeeded")).toBeDefined();
  });

  it("applies badge-error class for error tone", () => {
    const { container } = render(<StatusPill tone="error">Failed</StatusPill>);
    const el = container.firstElementChild;
    expect(el?.className).toMatch(/badge-error/);
  });

  it("applies badge-success class for success tone", () => {
    const { container } = render(<StatusPill tone="success">OK</StatusPill>);
    const el = container.firstElementChild;
    expect(el?.className).toMatch(/badge-success/);
  });

  it("applies neutral border class for neutral tone", () => {
    const { container } = render(<StatusPill tone="neutral">Pending</StatusPill>);
    const el = container.firstElementChild;
    expect(el?.className).toMatch(/color-border/);
  });

  it("renders as inline span", () => {
    const { container } = render(<StatusPill tone="info">Running</StatusPill>);
    expect(container.firstElementChild?.tagName).toBe("SPAN");
  });
});

describe("statusToneFor", () => {
  it("maps succeeded → success", () => {
    expect(statusToneFor("succeeded")).toBe("success");
  });

  it("maps failed → error", () => {
    expect(statusToneFor("failed")).toBe("error");
  });

  it("maps running → info", () => {
    expect(statusToneFor("running")).toBe("info");
  });

  it("maps approval_required → warning", () => {
    expect(statusToneFor("approval_required")).toBe("warning");
  });

  it("maps cancelled → neutral", () => {
    expect(statusToneFor("cancelled")).toBe("neutral");
  });

  it("maps pending → neutral", () => {
    expect(statusToneFor("pending")).toBe("neutral");
  });
});
