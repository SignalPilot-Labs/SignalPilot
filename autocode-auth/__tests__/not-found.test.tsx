import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import NotFound from "@/app/not-found";

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: null, status: "unauthenticated" }),
}));

describe("NotFound", () => {
  it("renders the 404 heading", () => {
    render(<NotFound />);
    expect(screen.getByRole("heading", { name: "404" })).toBeInTheDocument();
  });

  it("shows PAGE NOT FOUND text", () => {
    render(<NotFound />);
    expect(screen.getByText("PAGE NOT FOUND")).toBeInTheDocument();
  });

  it("has a back home link pointing to /", () => {
    render(<NotFound />);
    const link = screen.getByRole("link", { name: /back home/i });
    expect(link).toHaveAttribute("href", "/");
  });

  it("has a home logo link pointing to /", () => {
    render(<NotFound />);
    const link = screen.getByRole("link", { name: /signalpilot autocode/i });
    expect(link).toHaveAttribute("href", "/");
  });

  it("renders content within a main landmark", () => {
    render(<NotFound />);
    expect(screen.getByRole("main")).toBeInTheDocument();
  });

  it("renders a nav landmark for the header", () => {
    render(<NotFound />);
    expect(screen.getByRole("navigation", { name: /home/i })).toBeInTheDocument();
  });
});
