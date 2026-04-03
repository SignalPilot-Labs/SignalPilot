import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import AuthHeader from "@/components/AuthHeader";

vi.mock("next/image", () => ({
  default: (props: Record<string, unknown>) => {
    // eslint-disable-next-line @next/next/no-img-element, jsx-a11y/alt-text
    return <img {...props} />;
  },
}));

describe("AuthHeader", () => {
  // 1. Renders the SIGNALPILOT AUTOCODE logo link pointing to /
  it("renders the SIGNALPILOT AUTOCODE logo link pointing to /", () => {
    render(<AuthHeader />);
    const link = screen.getByRole("link", { name: /signalpilot autocode/i });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute("href", "/");
  });

  // 2. Logo link has navigation landmark with aria-label "Home"
  it("has navigation landmark with aria-label Home", () => {
    render(<AuthHeader />);
    expect(screen.getByRole("navigation", { name: "Home" })).toBeInTheDocument();
  });

  // 3. Does not render user info when user is null
  it("does not render user info when user is null", () => {
    render(<AuthHeader user={null} />);
    expect(screen.queryByRole("button", { name: /sign out/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/sign out/i)).not.toBeInTheDocument();
  });

  // 4. Does not render user info when user is undefined
  it("does not render user info when user is undefined", () => {
    render(<AuthHeader user={undefined} />);
    expect(screen.queryByRole("button", { name: /sign out/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/sign out/i)).not.toBeInTheDocument();
  });

  // 5. Shows user name when user has name
  it("shows user name when user has name", () => {
    render(<AuthHeader user={{ name: "Alice", email: "alice@example.com" }} />);
    expect(screen.getByText("Alice")).toBeInTheDocument();
  });

  // 6. Shows user email when user has no name but has email
  it("shows user email when user has no name but has email", () => {
    render(<AuthHeader user={{ name: null, email: "alice@example.com" }} />);
    expect(screen.getByText("alice@example.com")).toBeInTheDocument();
  });

  // 7. Shows avatar image when user has image URL
  it("shows avatar image when user has image URL", () => {
    render(<AuthHeader user={{ name: "Alice", image: "https://example.com/avatar.png" }} />);
    expect(screen.getByRole("img")).toBeInTheDocument();
    expect(screen.getByRole("img")).toHaveAttribute("src", "https://example.com/avatar.png");
  });

  // 8. Does not show avatar when user has no image
  it("does not show avatar when user has no image", () => {
    render(<AuthHeader user={{ name: "Alice", image: null }} />);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  // 9. Avatar uses user.name as alt text
  it("avatar uses user.name as alt text", () => {
    render(<AuthHeader user={{ name: "Alice", image: "https://example.com/avatar.png" }} />);
    expect(screen.getByRole("img")).toHaveAttribute("alt", "Alice");
  });

  // 10. Avatar falls back to "User avatar" alt text when no name
  it("avatar falls back to 'User avatar' alt text when no name", () => {
    render(<AuthHeader user={{ name: null, image: "https://example.com/avatar.png" }} />);
    expect(screen.getByRole("img")).toHaveAttribute("alt", "User avatar");
  });

  // 11. Renders sign out button
  it("renders sign out button", () => {
    render(<AuthHeader user={{ name: "Alice" }} />);
    expect(screen.getByRole("button", { name: /sign out/i })).toBeInTheDocument();
  });

  // 12. Sign out form uses POST method (not GET)
  it("sign out form uses POST method", () => {
    const { container } = render(<AuthHeader user={{ name: "Alice" }} />);
    const form = container.querySelector("form");
    expect(form).not.toBeNull();
    expect(form!.method).toBe("post");
  });

  // 13. Sign out form action points to /api/auth/signout
  it("sign out form action points to /api/auth/signout", () => {
    const { container } = render(<AuthHeader user={{ name: "Alice" }} />);
    const form = container.querySelector("form");
    expect(form).not.toBeNull();
    expect(form!.getAttribute("action")).toBe("/api/auth/signout");
  });
});
