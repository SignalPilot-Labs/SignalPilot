import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import Providers from "@/components/Providers";

vi.mock("next-auth/react", () => ({
  SessionProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

describe("Providers", () => {
  it("renders children within SessionProvider", () => {
    render(
      <Providers>
        <p>test content</p>
      </Providers>
    );
    expect(screen.getByText("test content")).toBeInTheDocument();
  });
});
