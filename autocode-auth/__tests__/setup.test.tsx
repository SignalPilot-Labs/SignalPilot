import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import SetupPage from "@/app/setup/page";

beforeEach(() => {
  vi.useFakeTimers();
  Object.assign(navigator, {
    clipboard: {
      writeText: vi.fn().mockResolvedValue(undefined),
    },
  });
});

afterEach(() => {
  vi.useRealTimers();
});

async function advance(ms: number) {
  await act(async () => {
    vi.advanceTimersByTime(ms);
  });
}

describe("SetupPage", () => {
  // 1. Renders SETUP heading
  it("renders SETUP heading", () => {
    render(<SetupPage />);
    expect(screen.getByRole("heading", { name: /setup/i })).toBeInTheDocument();
  });

  // 2. Renders install command
  it("renders install command", () => {
    render(<SetupPage />);
    expect(screen.getByText(/npm install -g signalpilot-autocode/)).toBeInTheDocument();
  });

  // 3. Renders signalpilot login command
  it("renders signalpilot login command", () => {
    render(<SetupPage />);
    // The command is shown in a <code> element; use getAllBy since it also appears in the description text
    const matches = screen.getAllByText(/signalpilot login/);
    expect(matches.length).toBeGreaterThanOrEqual(1);
    // The code element specifically contains the $ prefix
    expect(screen.getByText(/\$ signalpilot login/)).toBeInTheDocument();
  });

  // 4. Copy button works and shows COPIED
  it("copy button works and shows COPIED", async () => {
    render(<SetupPage />);
    fireEvent.click(screen.getByRole("button", { name: /\[copy\]/i }));
    await advance(0);
    expect(screen.getByRole("button", { name: /\[copied\]/i })).toBeInTheDocument();
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("npm install -g signalpilot-autocode");
  });

  // 5. Copy resets after timeout
  it("copy button resets to COPY after 2000ms", async () => {
    render(<SetupPage />);
    fireEvent.click(screen.getByRole("button", { name: /\[copy\]/i }));
    await advance(0);
    expect(screen.getByRole("button", { name: /\[copied\]/i })).toBeInTheDocument();
    await advance(2000);
    expect(screen.getByRole("button", { name: /\[copy\]/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /\[copied\]/i })).not.toBeInTheDocument();
  });

  // 6. Status indicators start as WAITING/CHECKING/PENDING
  it("status indicators start in initial waiting state", () => {
    render(<SetupPage />);
    expect(screen.getByText("WAITING...")).toBeInTheDocument();
    expect(screen.getByText("CHECKING...")).toBeInTheDocument();
    expect(screen.getByText("PENDING...")).toBeInTheDocument();
  });

  // 7. CLI status updates to CONNECTED after 800ms
  it("CLI status updates to CONNECTED after 800ms", async () => {
    render(<SetupPage />);
    expect(screen.queryByText(/CONNECTED ✓/)).not.toBeInTheDocument();
    await advance(800);
    expect(screen.getByText("CONNECTED ✓")).toBeInTheDocument();
  });

  // 8. Docker status updates to RUNNING after 1600ms
  it("Docker status updates to RUNNING after 1600ms", async () => {
    render(<SetupPage />);
    expect(screen.queryByText(/RUNNING ✓/)).not.toBeInTheDocument();
    await advance(1600);
    expect(screen.getByText("RUNNING ✓")).toBeInTheDocument();
  });

  // 9. Auth status updates to AUTHENTICATED after 2400ms
  it("Auth status updates to AUTHENTICATED after 2400ms", async () => {
    render(<SetupPage />);
    expect(screen.queryByText(/AUTHENTICATED/)).not.toBeInTheDocument();
    await advance(2400);
    expect(screen.getByText(/AUTHENTICATED/)).toBeInTheDocument();
  });

  // 10. Repo + mode appear after 3200ms
  it("repo and mode appear after 3200ms", async () => {
    render(<SetupPage />);
    expect(screen.getByText("NOT CONNECTED")).toBeInTheDocument();
    expect(screen.getByText("NOT SET")).toBeInTheDocument();
    await advance(3200);
    // The repo status indicator shows repo ✓; may appear in multiple places once terminal also renders
    const repoMatches = screen.getAllByText(/github\.com\/user\/repo ✓/);
    expect(repoMatches.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("AUTONOMOUS")).toBeInTheDocument();
  });

  // 11. Terminal starts streaming after all green
  it("terminal starts streaming lines after 3200ms", async () => {
    render(<SetupPage />);
    // Before all green: no terminal lines yet
    expect(screen.queryByText(/signalpilot run/)).not.toBeInTheDocument();
    await advance(3200 + 300);
    // First line: "$ signalpilot run --mode autonomous"
    expect(screen.getByText(/signalpilot run --mode autonomous/)).toBeInTheDocument();
  });

  // 12. Terminal shows all lines after full timing
  it("terminal shows all 10 lines after full timing", async () => {
    render(<SetupPage />);
    // 3200ms for statuses + 10 lines * 300ms each = 3200 + 3000 = 6200ms
    await advance(3200 + 10 * 300);
    expect(screen.getByText(/first improvement shipped/)).toBeInTheDocument();
  });

  // 13. Shows AUTOCODE IS RUNNING after completion
  it("shows AUTOCODE IS RUNNING after completion", async () => {
    render(<SetupPage />);
    await advance(3200 + 10 * 300);
    expect(screen.getByText("AUTOCODE IS RUNNING.")).toBeInTheDocument();
  });

  // 14. Shows OPEN DASHBOARD link after completion
  it("shows OPEN DASHBOARD link after completion", async () => {
    render(<SetupPage />);
    await advance(3200 + 10 * 300);
    const dashboardLink = screen.getByRole("link", { name: /open dashboard/i });
    expect(dashboardLink).toBeInTheDocument();
    expect(dashboardLink).toHaveAttribute("href", "/dashboard");
  });

  // 15. Terminal has aria-live polite
  it("terminal region has aria-live='polite'", () => {
    render(<SetupPage />);
    const log = screen.getByRole("log");
    expect(log).toHaveAttribute("aria-live", "polite");
  });

  // 16. Renders main landmark
  it("renders main landmark", () => {
    render(<SetupPage />);
    expect(screen.getByRole("main")).toBeInTheDocument();
  });

  // 17. Sign in link points to /signin
  it("sign in link points to /signin", () => {
    render(<SetupPage />);
    expect(screen.getByRole("link", { name: /sign in/i })).toHaveAttribute("href", "/signin");
  });
});
