import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { useSession } from "next-auth/react";
import AuthLayout from "@/components/AuthLayout";

vi.mock("next-auth/react", () => ({
  useSession: vi.fn(),
  signOut: vi.fn(),
}));

vi.mock("next/image", () => ({
  default: (props: Record<string, unknown>) => <img {...props} />,
}));

const mockUseSession = useSession as ReturnType<typeof vi.fn>;

describe("AuthLayout", () => {
  // 1. Renders a main landmark
  it("renders a main landmark", () => {
    mockUseSession.mockReturnValue({ data: null });
    render(<AuthLayout><p>content</p></AuthLayout>);
    expect(screen.getByRole("main")).toBeInTheDocument();
  });

  // 2. Renders children content
  it("renders children content", () => {
    mockUseSession.mockReturnValue({ data: null });
    render(<AuthLayout><p>child content</p></AuthLayout>);
    expect(screen.getByText("child content")).toBeInTheDocument();
  });

  // 3. Renders AuthHeader (nav with aria-label "Home")
  it("renders AuthHeader nav with aria-label Home", () => {
    mockUseSession.mockReturnValue({ data: null });
    render(<AuthLayout><span>anything</span></AuthLayout>);
    expect(screen.getByRole("navigation", { name: "Home" })).toBeInTheDocument();
  });

  // 4. Passes null user to AuthHeader when session is null — no user info shown
  it("does not show user info when session is null (unauthenticated)", () => {
    mockUseSession.mockReturnValue({ data: null });
    render(<AuthLayout><span>page</span></AuthLayout>);
    expect(screen.queryByRole("button", { name: /sign out/i })).not.toBeInTheDocument();
  });

  // 5. Passes session user to AuthHeader when authenticated — shows user name
  it("shows user name when session has a user", () => {
    mockUseSession.mockReturnValue({
      data: { user: { name: "Ada Lovelace", email: "ada@example.com", image: null } },
    });
    render(<AuthLayout><span>page</span></AuthLayout>);
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
  });

  // 6. Shows user avatar when session has image
  it("shows user avatar img when session user has an image", () => {
    mockUseSession.mockReturnValue({
      data: {
        user: {
          name: "Ada Lovelace",
          email: "ada@example.com",
          image: "https://example.com/avatar.png",
        },
      },
    });
    render(<AuthLayout><span>page</span></AuthLayout>);
    const avatar = screen.getByAltText("Ada Lovelace");
    expect(avatar).toBeInTheDocument();
    expect(avatar).toHaveAttribute("src", "https://example.com/avatar.png");
  });
});
