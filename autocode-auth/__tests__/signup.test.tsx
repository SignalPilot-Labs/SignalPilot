import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import SignupPage from "@/app/signup/page";

const pushMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

let logSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  pushMock.mockClear();
  logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
});

afterEach(() => {
  logSpy.mockRestore();
});

describe("SignupPage", () => {
  it("renders the GitHub OAuth button", () => {
    render(<SignupPage />);
    expect(screen.getByRole("button", { name: /continue with github/i })).toBeInTheDocument();
  });

  it("shows email error on blur with invalid email", () => {
    render(<SignupPage />);
    const emailInput = screen.getByLabelText(/email/i);
    fireEvent.change(emailInput, { target: { value: "notanemail" } });
    fireEvent.blur(emailInput);
    expect(screen.getByText("INVALID EMAIL")).toBeInTheDocument();
  });

  it("shows no email error for valid email", () => {
    render(<SignupPage />);
    const emailInput = screen.getByLabelText(/email/i);
    fireEvent.change(emailInput, { target: { value: "test@example.com" } });
    fireEvent.blur(emailInput);
    expect(screen.queryByText("INVALID EMAIL")).not.toBeInTheDocument();
  });

  it("shows password error on blur when too short", () => {
    render(<SignupPage />);
    const passwordInput = screen.getByLabelText(/password/i);
    fireEvent.change(passwordInput, { target: { value: "short" } });
    fireEvent.blur(passwordInput);
    expect(screen.getByText("MIN 8 CHARACTERS")).toBeInTheDocument();
  });

  it("shows no password error for valid password", () => {
    render(<SignupPage />);
    const passwordInput = screen.getByLabelText(/password/i);
    fireEvent.change(passwordInput, { target: { value: "longpassword" } });
    fireEvent.blur(passwordInput);
    expect(screen.queryByText("MIN 8 CHARACTERS")).not.toBeInTheDocument();
  });

  it("blocks submission with invalid inputs and shows errors", () => {
    render(<SignupPage />);
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));
    expect(screen.getByText("INVALID EMAIL")).toBeInTheDocument();
    expect(screen.getByText("MIN 8 CHARACTERS")).toBeInTheDocument();
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("redirects to /setup on valid submission", () => {
    render(<SignupPage />);
    const emailInput = screen.getByLabelText(/email/i);
    const passwordInput = screen.getByLabelText(/password/i);
    fireEvent.change(emailInput, { target: { value: "test@example.com" } });
    fireEvent.change(passwordInput, { target: { value: "longpassword" } });
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));
    expect(pushMock).toHaveBeenCalledWith("/setup");
  });

  it("logs email on valid submission without password", () => {
    render(<SignupPage />);
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "test@example.com" } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "longpassword" } });
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));
    expect(logSpy).toHaveBeenCalledWith("[signup] email/password submit", { email: "test@example.com" });
    // Password must NEVER appear in log output
    const allArgs = logSpy.mock.calls.flat().map(String).join(" ");
    expect(allArgs).not.toContain("longpassword");
  });

  it("logs github oauth on GitHub button click", () => {
    render(<SignupPage />);
    fireEvent.click(screen.getByRole("button", { name: /continue with github/i }));
    expect(logSpy).toHaveBeenCalledWith("[signup] github oauth initiated");
  });

  it("submits form on Enter key press in password field", () => {
    render(<SignupPage />);
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "test@example.com" } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "longpassword" } });
    fireEvent.submit(screen.getByLabelText(/password/i).closest("form")!);
    expect(pushMock).toHaveBeenCalledWith("/setup");
  });

  it("does not submit form on Enter with invalid inputs", () => {
    render(<SignupPage />);
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "bad" } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "short" } });
    fireEvent.submit(screen.getByLabelText(/password/i).closest("form")!);
    expect(pushMock).not.toHaveBeenCalled();
    expect(screen.getByText("INVALID EMAIL")).toBeInTheDocument();
    expect(screen.getByText("MIN 8 CHARACTERS")).toBeInTheDocument();
  });

  it("GitHub button is the first focusable element after the header", () => {
    const { container } = render(<SignupPage />);
    const focusable = Array.from(container.querySelectorAll("a[href], button, input"));
    const headerLink = focusable.find((el) => el.textContent?.includes("SIGNALPILOT AUTOCODE"));
    const headerIndex = focusable.indexOf(headerLink!);
    const githubButton = screen.getByRole("button", { name: /continue with github/i });
    expect(focusable[headerIndex + 1]).toBe(githubButton);
  });

  it("email input has correct autocomplete attribute", () => {
    render(<SignupPage />);
    expect(screen.getByLabelText(/email/i)).toHaveAttribute("autocomplete", "email");
  });

  it("password input has correct autocomplete attribute", () => {
    render(<SignupPage />);
    expect(screen.getByLabelText(/password/i)).toHaveAttribute("autocomplete", "new-password");
  });

  it("disables form inputs during submission", () => {
    render(<SignupPage />);
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "test@example.com" } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "longpassword" } });
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));
    expect(screen.getByLabelText(/email/i)).toBeDisabled();
    expect(screen.getByLabelText(/password/i)).toBeDisabled();
  });

  it("shows CREATING... text during email submission", () => {
    render(<SignupPage />);
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "test@example.com" } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "longpassword" } });
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));
    expect(screen.getByRole("button", { name: /creating/i })).toBeInTheDocument();
  });

  it("shows REDIRECTING... text during GitHub submission", () => {
    render(<SignupPage />);
    fireEvent.click(screen.getByRole("button", { name: /continue with github/i }));
    expect(screen.getByRole("button", { name: /redirecting/i })).toBeInTheDocument();
  });

  it("disables GitHub button during email submission", () => {
    render(<SignupPage />);
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "test@example.com" } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "longpassword" } });
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));
    expect(screen.getByRole("button", { name: /continue with github/i })).toBeDisabled();
  });

  it("signup validation errors have role=alert", () => {
    render(<SignupPage />);
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));
    expect(screen.getAllByRole("alert")).toHaveLength(2);
  });

  it("Terms and Privacy links have correct hrefs", () => {
    render(<SignupPage />);
    expect(screen.getByRole("link", { name: "Terms" })).toHaveAttribute("href", "/terms");
    expect(screen.getByRole("link", { name: "Privacy" })).toHaveAttribute("href", "/privacy");
  });

  it("renders main landmark", () => {
    render(<SignupPage />);
    expect(screen.getByRole("main")).toBeInTheDocument();
  });
});
