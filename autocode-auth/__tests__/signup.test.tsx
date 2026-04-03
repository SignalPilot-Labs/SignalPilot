import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import SignupPage from "@/app/signup/page";

const pushMock = vi.fn();
const signInMock = vi.fn().mockResolvedValue({ error: null });

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock("next-auth/react", () => ({
  signIn: (...args: unknown[]) => signInMock(...args),
  useSession: () => ({ data: null, status: "unauthenticated" }),
}));

const fetchMock = vi.fn();
global.fetch = fetchMock as unknown as typeof fetch;

let logSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  pushMock.mockClear();
  signInMock.mockClear();
  signInMock.mockResolvedValue({ error: null });
  fetchMock.mockClear();
  fetchMock.mockResolvedValue({
    ok: true,
    json: async () => ({}),
  });
  logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
});

afterEach(() => {
  logSpy.mockRestore();
});

describe("SignupPage", () => {
  // 1. Renders GitHub OAuth button
  it("renders GitHub OAuth button", () => {
    render(<SignupPage />);
    expect(screen.getByRole("button", { name: /continue with github/i })).toBeInTheDocument();
  });

  // 2. Renders Google OAuth button
  it("renders Google OAuth button", () => {
    render(<SignupPage />);
    expect(screen.getByRole("button", { name: /continue with google/i })).toBeInTheDocument();
  });

  // 3. GitHub button calls signIn with correct args
  it("GitHub button calls signIn with correct args", () => {
    render(<SignupPage />);
    fireEvent.click(screen.getByRole("button", { name: /continue with github/i }));
    expect(signInMock).toHaveBeenCalledWith("github", { callbackUrl: "/setup" });
  });

  // 4. Google button calls signIn with correct args
  it("Google button calls signIn with correct args", () => {
    render(<SignupPage />);
    fireEvent.click(screen.getByRole("button", { name: /continue with google/i }));
    expect(signInMock).toHaveBeenCalledWith("google", { callbackUrl: "/setup" });
  });

  // 5. Shows email error on blur with invalid email
  it("shows email error on blur with invalid email", () => {
    render(<SignupPage />);
    const emailInput = screen.getByLabelText(/email/i);
    fireEvent.change(emailInput, { target: { value: "notanemail" } });
    fireEvent.blur(emailInput);
    expect(screen.getByText("INVALID EMAIL")).toBeInTheDocument();
  });

  // 6. Shows no email error for valid email
  it("shows no email error for valid email", () => {
    render(<SignupPage />);
    const emailInput = screen.getByLabelText(/email/i);
    fireEvent.change(emailInput, { target: { value: "test@example.com" } });
    fireEvent.blur(emailInput);
    expect(screen.queryByText("INVALID EMAIL")).not.toBeInTheDocument();
  });

  // 7. Shows password error on blur when too short
  it("shows password error on blur when too short", () => {
    render(<SignupPage />);
    const passwordInput = screen.getByLabelText(/password/i);
    fireEvent.change(passwordInput, { target: { value: "short" } });
    fireEvent.blur(passwordInput);
    expect(screen.getByText("MIN 8 CHARACTERS")).toBeInTheDocument();
  });

  // 8. Shows no password error for valid password
  it("shows no password error for valid password", () => {
    render(<SignupPage />);
    const passwordInput = screen.getByLabelText(/password/i);
    fireEvent.change(passwordInput, { target: { value: "longpassword" } });
    fireEvent.blur(passwordInput);
    expect(screen.queryByText("MIN 8 CHARACTERS")).not.toBeInTheDocument();
  });

  // 9. Blocks submission with invalid inputs
  it("blocks submission with invalid inputs and shows errors", () => {
    render(<SignupPage />);
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));
    expect(screen.getByText("INVALID EMAIL")).toBeInTheDocument();
    expect(screen.getByText("MIN 8 CHARACTERS")).toBeInTheDocument();
    expect(pushMock).not.toHaveBeenCalled();
  });

  // 10. Email submission calls fetch then signIn then router.push
  it("email submission calls fetch then signIn then router.push", async () => {
    render(<SignupPage />);
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "test@example.com" } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "longpassword" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /create account/i }));
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/auth/signup", expect.objectContaining({ method: "POST" }));
    expect(signInMock).toHaveBeenCalledWith("credentials", expect.objectContaining({ email: "test@example.com", password: "longpassword", redirect: false }));
    expect(pushMock).toHaveBeenCalledWith("/setup");
  });

  // 11. Shows CREATING... during email submission
  it("shows CREATING... during email submission", async () => {
    // Make fetch hang so we can observe the in-flight state
    let resolveFetch!: () => void;
    fetchMock.mockReturnValue(
      new Promise<Response>((resolve) => {
        resolveFetch = () =>
          resolve({ ok: true, json: async () => ({}) } as Response);
      })
    );
    render(<SignupPage />);
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "test@example.com" } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "longpassword" } });
    act(() => {
      fireEvent.click(screen.getByRole("button", { name: /create account/i }));
    });
    expect(screen.getByRole("button", { name: /creating/i })).toBeInTheDocument();
    // Clean up: resolve the promise
    await act(async () => { resolveFetch(); });
  });

  // 12. Shows REDIRECTING... during GitHub submission
  it("shows REDIRECTING... during GitHub submission", () => {
    render(<SignupPage />);
    fireEvent.click(screen.getByRole("button", { name: /continue with github/i }));
    expect(screen.getByRole("button", { name: /redirecting/i })).toBeInTheDocument();
  });

  // 13. Shows REDIRECTING... during Google submission
  it("shows REDIRECTING... during Google submission", () => {
    render(<SignupPage />);
    fireEvent.click(screen.getByRole("button", { name: /continue with google/i }));
    expect(screen.getByRole("button", { name: /redirecting/i })).toBeInTheDocument();
  });

  // 14. Disables buttons during submission
  it("disables buttons during GitHub submission", () => {
    render(<SignupPage />);
    fireEvent.click(screen.getByRole("button", { name: /continue with github/i }));
    const buttons = screen.getAllByRole("button");
    for (const btn of buttons) {
      expect(btn).toBeDisabled();
    }
  });

  // 15. Shows API error when fetch fails
  it("shows API error when fetch returns error response", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      json: async () => ({ error: "EMAIL_EXISTS" }),
    });
    render(<SignupPage />);
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "test@example.com" } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "longpassword" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /create account/i }));
    });
    expect(screen.getByText("EMAIL_EXISTS")).toBeInTheDocument();
    expect(pushMock).not.toHaveBeenCalled();
  });

  // 16. Terms and Privacy links have correct hrefs
  it("Terms and Privacy links have correct hrefs", () => {
    render(<SignupPage />);
    expect(screen.getByRole("link", { name: "Terms" })).toHaveAttribute("href", "/terms");
    expect(screen.getByRole("link", { name: "Privacy" })).toHaveAttribute("href", "/privacy");
  });

  // 17. Sign in link points to /signin
  it("sign in link points to /signin", () => {
    render(<SignupPage />);
    expect(screen.getByRole("link", { name: /sign in/i })).toHaveAttribute("href", "/signin");
  });

  // 18. Renders main landmark
  it("renders main landmark", () => {
    render(<SignupPage />);
    expect(screen.getByRole("main")).toBeInTheDocument();
  });

  // 19. Email input has autocomplete="email"
  it("email input has autocomplete='email'", () => {
    render(<SignupPage />);
    expect(screen.getByLabelText(/email/i)).toHaveAttribute("autocomplete", "email");
  });

  // 20. Password input has autocomplete="new-password"
  it("password input has autocomplete='new-password'", () => {
    render(<SignupPage />);
    expect(screen.getByLabelText(/password/i)).toHaveAttribute("autocomplete", "new-password");
  });

  // 21. Logs github oauth on click (console.log spy)
  it("logs github oauth on GitHub button click", () => {
    render(<SignupPage />);
    fireEvent.click(screen.getByRole("button", { name: /continue with github/i }));
    expect(logSpy).toHaveBeenCalledWith("[signup] github oauth initiated");
  });

  // 22. Logs email on submit without password in logs
  it("logs email on submit and does not log password", async () => {
    render(<SignupPage />);
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "test@example.com" } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "longpassword" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /create account/i }));
    });
    expect(logSpy).toHaveBeenCalledWith("[signup] email/password submit", { email: "test@example.com" });
    const allArgs = logSpy.mock.calls.flat().map(String).join(" ");
    expect(allArgs).not.toContain("longpassword");
  });
});
