import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import OAuthButtons from "@/components/OAuthButtons";

describe("OAuthButtons", () => {
  // 1. Renders GitHub button with default label
  it("renders GitHub button with default label 'CONTINUE WITH GITHUB'", () => {
    render(<OAuthButtons onGitHub={vi.fn()} onGoogle={vi.fn()} disabled={false} />);
    expect(screen.getByRole("button", { name: "CONTINUE WITH GITHUB" })).toBeInTheDocument();
  });

  // 2. Renders Google button with default label
  it("renders Google button with default label 'CONTINUE WITH GOOGLE'", () => {
    render(<OAuthButtons onGitHub={vi.fn()} onGoogle={vi.fn()} disabled={false} />);
    expect(screen.getByRole("button", { name: "CONTINUE WITH GOOGLE" })).toBeInTheDocument();
  });

  // 3. GitHub button calls onGitHub when clicked
  it("calls onGitHub when GitHub button is clicked", () => {
    const onGitHub = vi.fn();
    render(<OAuthButtons onGitHub={onGitHub} onGoogle={vi.fn()} disabled={false} />);
    fireEvent.click(screen.getByRole("button", { name: "CONTINUE WITH GITHUB" }));
    expect(onGitHub).toHaveBeenCalledTimes(1);
  });

  // 4. Google button calls onGoogle when clicked
  it("calls onGoogle when Google button is clicked", () => {
    const onGoogle = vi.fn();
    render(<OAuthButtons onGitHub={vi.fn()} onGoogle={onGoogle} disabled={false} />);
    fireEvent.click(screen.getByRole("button", { name: "CONTINUE WITH GOOGLE" }));
    expect(onGoogle).toHaveBeenCalledTimes(1);
  });

  // 5. Custom githubLabel overrides default text
  it("renders custom githubLabel when provided", () => {
    render(
      <OAuthButtons
        onGitHub={vi.fn()}
        onGoogle={vi.fn()}
        disabled={false}
        githubLabel="LOGIN WITH GITHUB"
      />
    );
    expect(screen.getByRole("button", { name: "LOGIN WITH GITHUB" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "CONTINUE WITH GITHUB" })).not.toBeInTheDocument();
  });

  // 6. Custom googleLabel overrides default text
  it("renders custom googleLabel when provided", () => {
    render(
      <OAuthButtons
        onGitHub={vi.fn()}
        onGoogle={vi.fn()}
        disabled={false}
        googleLabel="LOGIN WITH GOOGLE"
      />
    );
    expect(screen.getByRole("button", { name: "LOGIN WITH GOOGLE" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "CONTINUE WITH GOOGLE" })).not.toBeInTheDocument();
  });

  // 7. Both buttons are disabled when disabled=true
  it("disables both buttons when disabled=true", () => {
    render(<OAuthButtons onGitHub={vi.fn()} onGoogle={vi.fn()} disabled={true} />);
    expect(screen.getByRole("button", { name: "CONTINUE WITH GITHUB" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "CONTINUE WITH GOOGLE" })).toBeDisabled();
  });

  // 8. Both buttons are enabled when disabled=false
  it("enables both buttons when disabled=false", () => {
    render(<OAuthButtons onGitHub={vi.fn()} onGoogle={vi.fn()} disabled={false} />);
    expect(screen.getByRole("button", { name: "CONTINUE WITH GITHUB" })).not.toBeDisabled();
    expect(screen.getByRole("button", { name: "CONTINUE WITH GOOGLE" })).not.toBeDisabled();
  });

  // 9. Renders the OR divider text
  it("renders the OR divider", () => {
    render(<OAuthButtons onGitHub={vi.fn()} onGoogle={vi.fn()} disabled={false} />);
    expect(screen.getByText("OR")).toBeInTheDocument();
  });

  // 10. Does not call handlers when disabled
  it("does not call onGitHub when GitHub button is clicked while disabled", () => {
    const onGitHub = vi.fn();
    render(<OAuthButtons onGitHub={onGitHub} onGoogle={vi.fn()} disabled={true} />);
    fireEvent.click(screen.getByRole("button", { name: "CONTINUE WITH GITHUB" }));
    expect(onGitHub).not.toHaveBeenCalled();
  });

  it("does not call onGoogle when Google button is clicked while disabled", () => {
    const onGoogle = vi.fn();
    render(<OAuthButtons onGitHub={vi.fn()} onGoogle={onGoogle} disabled={true} />);
    fireEvent.click(screen.getByRole("button", { name: "CONTINUE WITH GOOGLE" }));
    expect(onGoogle).not.toHaveBeenCalled();
  });
});
