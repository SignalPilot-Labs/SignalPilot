import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import SigninPage from "@/app/signin/page";

const pushMock = vi.fn();
const signInMock = vi.fn().mockResolvedValue({ error: null });

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock("next-auth/react", () => ({
  signIn: (...args: unknown[]) => signInMock(...args),
  useSession: () => ({ data: null, status: "unauthenticated" }),
}));

beforeEach(() => {
  pushMock.mockClear();
  signInMock.mockClear();
  signInMock.mockResolvedValue({ error: null });
});

describe("SigninPage", () => {
  // 1. Renders SIGN IN heading
  it("renders SIGN IN heading", () => {
    render(<SigninPage />);
    expect(screen.getByRole("heading", { name: /sign in/i })).toBeInTheDocument();
  });

  // 2. Renders GitHub button
  it("renders GitHub button", () => {
    render(<SigninPage />);
    expect(screen.getByRole("button", { name: /continue with github/i })).toBeInTheDocument();
  });

  // 3. Renders Google button
  it("renders Google button", () => {
    render(<SigninPage />);
    expect(screen.getByRole("button", { name: /continue with google/i })).toBeInTheDocument();
  });

  // 4. GitHub calls signIn with correct args
  it("GitHub button calls signIn with correct args", () => {
    render(<SigninPage />);
    fireEvent.click(screen.getByRole("button", { name: /continue with github/i }));
    expect(signInMock).toHaveBeenCalledWith("github", { callbackUrl: "/setup" });
  });

  // 5. Google calls signIn with correct args
  it("Google button calls signIn with correct args", () => {
    render(<SigninPage />);
    fireEvent.click(screen.getByRole("button", { name: /continue with google/i }));
    expect(signInMock).toHaveBeenCalledWith("google", { callbackUrl: "/setup" });
  });

  // 6. Shows email error on blur
  it("shows INVALID EMAIL error on blur with invalid email", () => {
    render(<SigninPage />);
    const emailInput = screen.getByLabelText(/email/i);
    fireEvent.change(emailInput, { target: { value: "notanemail" } });
    fireEvent.blur(emailInput);
    expect(screen.getByText("INVALID EMAIL")).toBeInTheDocument();
  });

  // 7. Shows REQUIRED password error on blur when empty
  it("shows REQUIRED password error on blur when empty", () => {
    render(<SigninPage />);
    const passwordInput = screen.getByLabelText(/password/i);
    fireEvent.blur(passwordInput);
    expect(screen.getByText("REQUIRED")).toBeInTheDocument();
  });

  // 8. Blocks submission with empty inputs
  it("blocks submission with empty inputs", () => {
    render(<SigninPage />);
    fireEvent.click(screen.getByRole("button", { name: /^sign in$/i }));
    expect(signInMock).not.toHaveBeenCalled();
    expect(pushMock).not.toHaveBeenCalled();
  });

  // 9. Valid submit calls signIn credentials then router.push
  it("valid submit calls signIn credentials then router.push('/setup')", async () => {
    render(<SigninPage />);
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "user@example.com" } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "mypassword" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^sign in$/i }));
    });
    expect(signInMock).toHaveBeenCalledWith("credentials", {
      email: "user@example.com",
      password: "mypassword",
      redirect: false,
    });
    expect(pushMock).toHaveBeenCalledWith("/setup");
  });

  // 10. Shows INVALID CREDENTIALS on signIn error
  it("shows INVALID CREDENTIALS when signIn returns error", async () => {
    signInMock.mockResolvedValue({ error: "CredentialsSignin" });
    render(<SigninPage />);
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "user@example.com" } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "wrongpass" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^sign in$/i }));
    });
    expect(screen.getByText("INVALID CREDENTIALS")).toBeInTheDocument();
    expect(pushMock).not.toHaveBeenCalled();
  });

  // 11. Shows SIGNING IN... during submission
  it("shows SIGNING IN... during submission", async () => {
    let resolveSignIn!: (value: { error: null }) => void;
    signInMock.mockReturnValue(
      new Promise<{ error: null }>((resolve) => {
        resolveSignIn = resolve;
      })
    );
    render(<SigninPage />);
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "user@example.com" } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "mypassword" } });
    act(() => {
      fireEvent.click(screen.getByRole("button", { name: /^sign in$/i }));
    });
    expect(screen.getByRole("button", { name: /signing in/i })).toBeInTheDocument();
    // Clean up
    await act(async () => { resolveSignIn({ error: null }); });
  });

  // 12. Shows REDIRECTING... for OAuth
  it("shows REDIRECTING... when GitHub is clicked", () => {
    render(<SigninPage />);
    fireEvent.click(screen.getByRole("button", { name: /continue with github/i }));
    expect(screen.getByRole("button", { name: /redirecting/i })).toBeInTheDocument();
  });

  // 13. Disables buttons during submission
  it("disables all buttons during GitHub OAuth submission", () => {
    render(<SigninPage />);
    fireEvent.click(screen.getByRole("button", { name: /continue with github/i }));
    const buttons = screen.getAllByRole("button");
    for (const btn of buttons) {
      expect(btn).toBeDisabled();
    }
  });

  // 14. Sign up link points to /signup
  it("sign up link points to /signup", () => {
    render(<SigninPage />);
    expect(screen.getByRole("link", { name: /sign up/i })).toHaveAttribute("href", "/signup");
  });

  // 15. Email input has autocomplete="email"
  it("email input has autocomplete='email'", () => {
    render(<SigninPage />);
    expect(screen.getByLabelText(/email/i)).toHaveAttribute("autocomplete", "email");
  });

  // 16. Password input has autocomplete="current-password"
  it("password input has autocomplete='current-password'", () => {
    render(<SigninPage />);
    expect(screen.getByLabelText(/password/i)).toHaveAttribute("autocomplete", "current-password");
  });

  // 17. Renders main landmark
  it("renders main landmark", () => {
    render(<SigninPage />);
    expect(screen.getByRole("main")).toBeInTheDocument();
  });
});
