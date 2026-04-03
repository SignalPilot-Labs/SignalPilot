import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import SetupPage from "@/app/setup/page";

let logSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  vi.useFakeTimers();
  logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
  Object.assign(navigator, {
    clipboard: {
      writeText: vi.fn().mockResolvedValue(undefined),
    },
  });
});

afterEach(() => {
  logSpy.mockRestore();
  vi.useRealTimers();
});

/** Advance fake timers and flush pending microtasks (e.g. clipboard Promise). */
async function advance(ms: number) {
  await act(async () => {
    vi.advanceTimersByTime(ms);
  });
}

/** Navigate from step 1 to step 3 (connect repo complete). */
async function advanceToStep3() {
  fireEvent.click(screen.getByRole("button", { name: /i've run this/i }));
  const repoInput = screen.getByLabelText(/paste your github repo url/i);
  fireEvent.change(repoInput, { target: { value: "https://github.com/user/repo" } });
  fireEvent.click(screen.getByRole("button", { name: /^connect$/i }));
  await advance(1200);
}

describe("SetupPage", () => {
  it("renders step 1 as active with I'VE RUN THIS button", () => {
    render(<SetupPage />);
    expect(screen.getByRole("heading", { name: /install cli/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /i've run this/i })).toBeInTheDocument();
  });

  it("renders locked steps with pointer-events-none", () => {
    render(<SetupPage />);
    const step2Section = screen.getByRole("heading", { name: /connect repo/i }).closest("section");
    expect(step2Section?.className).toContain("pointer-events-none");
  });

  it("advances from step 1 to step 2 on button click", () => {
    render(<SetupPage />);
    fireEvent.click(screen.getByRole("button", { name: /i've run this/i }));
    const repoInput = screen.getByLabelText(/paste your github repo url/i);
    expect(repoInput).not.toBeDisabled();
    expect(screen.getByRole("button", { name: /^connect$/i })).toBeInTheDocument();
  });

  it("updates copy button text to COPIED on click", async () => {
    render(<SetupPage />);
    const copyButton = screen.getByRole("button", { name: /copy/i });
    fireEvent.click(copyButton);
    // Flush the clipboard Promise microtask
    await advance(0);
    expect(screen.getByRole("button", { name: /copied/i })).toBeInTheDocument();
  });

  it("sets aria-checked on selected mode button", async () => {
    render(<SetupPage />);
    await advanceToStep3();
    const autonomousBtn = screen.getByRole("radio", { name: /autonomous/i });
    fireEvent.click(autonomousBtn);
    expect(autonomousBtn).toHaveAttribute("aria-checked", "true");
  });

  it("completes the full wizard flow end-to-end", async () => {
    render(<SetupPage />);
    // Step 1 → 2
    fireEvent.click(screen.getByRole("button", { name: /i've run this/i }));
    // Step 2: connect repo
    const repoInput = screen.getByLabelText(/paste your github repo url/i);
    fireEvent.change(repoInput, { target: { value: "https://github.com/user/repo" } });
    fireEvent.click(screen.getByRole("button", { name: /^connect$/i }));
    await advance(1200);
    expect(screen.getByText(/847 files indexed/)).toBeInTheDocument();
    // Step 3: select mode
    fireEvent.click(screen.getByRole("radio", { name: /autonomous/i }));
    await advance(300);
    // Step 4: start run
    expect(screen.getByRole("button", { name: /start autocode/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /start autocode/i }));
    // 11 terminal lines × 400ms each = 4400ms
    await advance(4400);
    expect(screen.getByText(/autocode is running/i)).toBeInTheDocument();
  });

  it("rejects invalid repo URLs", () => {
    render(<SetupPage />);
    fireEvent.click(screen.getByRole("button", { name: /i've run this/i }));
    const repoInput = screen.getByLabelText(/paste your github repo url/i);
    fireEvent.change(repoInput, { target: { value: "not-a-github-url" } });
    fireEvent.click(screen.getByRole("button", { name: /^connect$/i }));
    expect(screen.getByRole("button", { name: /^connect$/i })).toBeInTheDocument();
    const step3Section = screen.getByRole("heading", { name: /select mode/i }).closest("section");
    expect(step3Section?.className).toContain("pointer-events-none");
  });

  it("rejects github.com root URL with no owner or repo", () => {
    render(<SetupPage />);
    fireEvent.click(screen.getByRole("button", { name: /i've run this/i }));
    const repoInput = screen.getByLabelText(/paste your github repo url/i);
    fireEvent.change(repoInput, { target: { value: "https://github.com/" } });
    fireEvent.click(screen.getByRole("button", { name: /^connect$/i }));
    expect(screen.getByText("ENTER A VALID GITHUB REPO URL")).toBeInTheDocument();
    const step3Section = screen.getByRole("heading", { name: /select mode/i }).closest("section");
    expect(step3Section?.className).toContain("pointer-events-none");
  });

  it("rejects repo URLs with query strings", () => {
    render(<SetupPage />);
    fireEvent.click(screen.getByRole("button", { name: /i've run this/i }));
    const repoInput = screen.getByLabelText(/paste your github repo url/i);
    fireEvent.change(repoInput, { target: { value: "https://github.com/user/repo?evil=true" } });
    fireEvent.click(screen.getByRole("button", { name: /^connect$/i }));
    expect(screen.getByText("ENTER A VALID GITHUB REPO URL")).toBeInTheDocument();
    const step3Section = screen.getByRole("heading", { name: /select mode/i }).closest("section");
    expect(step3Section?.className).toContain("pointer-events-none");
  });

  it("rejects empty repo URL", () => {
    render(<SetupPage />);
    fireEvent.click(screen.getByRole("button", { name: /i've run this/i }));
    fireEvent.click(screen.getByRole("button", { name: /^connect$/i }));
    expect(screen.getByRole("button", { name: /^connect$/i })).toBeInTheDocument();
  });

  it("sets tabIndex={-1} on locked step inputs", () => {
    render(<SetupPage />);
    const repoInput = screen.getByLabelText(/paste your github repo url/i);
    expect(repoInput).toHaveAttribute("tabindex", "-1");
    const radios = screen.getAllByRole("radio");
    for (const radio of radios) {
      expect(radio).toHaveAttribute("tabindex", "-1");
    }
  });

  it("shows checkmark on completed step", () => {
    render(<SetupPage />);
    const step1Heading = screen.getByRole("heading", { name: /install cli/i });
    const step1Indicator = step1Heading.previousElementSibling!;
    expect(step1Indicator.textContent).toBe("01");
    fireEvent.click(screen.getByRole("button", { name: /i've run this/i }));
    expect(step1Indicator.textContent).toContain("✓");
  });

  it("submits repo URL on Enter key press", async () => {
    render(<SetupPage />);
    fireEvent.click(screen.getByRole("button", { name: /i've run this/i }));
    const repoInput = screen.getByLabelText(/paste your github repo url/i);
    fireEvent.change(repoInput, { target: { value: "https://github.com/user/repo" } });
    fireEvent.keyDown(repoInput, { key: "Enter" });
    await advance(1200);
    expect(screen.getByText(/847 files indexed/)).toBeInTheDocument();
    const step3Section = screen.getByRole("heading", { name: /select mode/i }).closest("section");
    expect(step3Section?.className).not.toContain("pointer-events-none");
  });

  it("terminal output uses the selected mode", async () => {
    render(<SetupPage />);
    await advanceToStep3();
    // Select SUPERVISED mode
    fireEvent.click(screen.getByRole("radio", { name: /supervised/i }));
    await advance(300);
    // Start run
    fireEvent.click(screen.getByRole("button", { name: /start autocode/i }));
    // 11 lines × 400ms
    await advance(4400);
    expect(screen.getByText(/--mode supervised/)).toBeInTheDocument();
  });

  it("shows error when connecting with invalid repo URL", () => {
    render(<SetupPage />);
    fireEvent.click(screen.getByRole("button", { name: /i've run this/i }));
    const repoInput = screen.getByLabelText(/paste your github repo url/i);
    fireEvent.change(repoInput, { target: { value: "not-a-github-url" } });
    fireEvent.click(screen.getByRole("button", { name: /^connect$/i }));
    expect(screen.getByText("ENTER A VALID GITHUB REPO URL")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("ENTER A VALID GITHUB REPO URL");
  });

  it("clears repo error when user types", () => {
    render(<SetupPage />);
    fireEvent.click(screen.getByRole("button", { name: /i've run this/i }));
    const repoInput = screen.getByLabelText(/paste your github repo url/i);
    fireEvent.click(screen.getByRole("button", { name: /^connect$/i }));
    expect(screen.getByText("ENTER A VALID GITHUB REPO URL")).toBeInTheDocument();
    fireEvent.change(repoInput, { target: { value: "h" } });
    expect(screen.queryByText("ENTER A VALID GITHUB REPO URL")).not.toBeInTheDocument();
  });

  it("logs repo URL when connecting", async () => {
    render(<SetupPage />);
    fireEvent.click(screen.getByRole("button", { name: /i've run this/i }));
    const repoInput = screen.getByLabelText(/paste your github repo url/i);
    fireEvent.change(repoInput, { target: { value: "https://github.com/user/repo" } });
    fireEvent.click(screen.getByRole("button", { name: /^connect$/i }));
    expect(logSpy).toHaveBeenCalledWith("[setup] connecting repo", { url: "https://github.com/user/repo" });
  });

  it("focuses repo input when advancing to step 2", () => {
    render(<SetupPage />);
    fireEvent.click(screen.getByRole("button", { name: /i've run this/i }));
    const repoInput = screen.getByLabelText(/paste your github repo url/i);
    expect(document.activeElement).toBe(repoInput);
  });

  it("focuses mode group when advancing to step 3", async () => {
    render(<SetupPage />);
    await advanceToStep3();
    const modeGroup = screen.getByRole("radiogroup");
    expect(document.activeElement).toBe(modeGroup);
  });

  it("focuses start button when advancing to step 4", async () => {
    render(<SetupPage />);
    await advanceToStep3();
    fireEvent.click(screen.getByRole("radio", { name: /autonomous/i }));
    await advance(300);
    const startButton = screen.getByRole("button", { name: /start autocode/i });
    expect(document.activeElement).toBe(startButton);
  });

  it("resets copy button text back to COPY after timeout", async () => {
    render(<SetupPage />);
    fireEvent.click(screen.getByRole("button", { name: /copy/i }));
    await advance(0);
    expect(screen.getByRole("button", { name: /copied/i })).toBeInTheDocument();
    await advance(2000);
    expect(screen.queryByRole("button", { name: /copied/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /copy/i })).toBeInTheDocument();
  });

  it("calls clipboard.writeText with the install command", async () => {
    render(<SetupPage />);
    fireEvent.click(screen.getByRole("button", { name: /copy/i }));
    await advance(0);
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("npx signalpilot-autocode init");
  });

  it("shows CONNECTING... during repo connection", async () => {
    render(<SetupPage />);
    fireEvent.click(screen.getByRole("button", { name: /i've run this/i }));
    const repoInput = screen.getByLabelText(/paste your github repo url/i);
    fireEvent.change(repoInput, { target: { value: "https://github.com/user/repo" } });
    fireEvent.click(screen.getByRole("button", { name: /^connect$/i }));
    expect(screen.getByRole("button", { name: /connecting\.\.\./i })).toBeInTheDocument();
  });

  it("displays OPEN DASHBOARD link after terminal completes", async () => {
    render(<SetupPage />);
    await advanceToStep3();
    fireEvent.click(screen.getByRole("radio", { name: /autonomous/i }));
    await advance(300);
    fireEvent.click(screen.getByRole("button", { name: /start autocode/i }));
    await advance(4400);
    expect(screen.getByRole("link", { name: /open dashboard/i })).toBeInTheDocument();
  });

  it("logs mode selection", async () => {
    render(<SetupPage />);
    await advanceToStep3();
    fireEvent.click(screen.getByRole("radio", { name: /autonomous/i }));
    expect(logSpy).toHaveBeenCalledWith("[setup] mode selected", { mode: "autonomous" });
  });

  it("logs first run start", async () => {
    render(<SetupPage />);
    await advanceToStep3();
    fireEvent.click(screen.getByRole("radio", { name: /autonomous/i }));
    await advance(300);
    fireEvent.click(screen.getByRole("button", { name: /start autocode/i }));
    expect(logSpy).toHaveBeenCalledWith("[setup] starting first run", { mode: "autonomous" });
  });

  it("terminal output region has aria-live polite", async () => {
    render(<SetupPage />);
    await advanceToStep3();
    fireEvent.click(screen.getByRole("radio", { name: /autonomous/i }));
    await advance(300);
    fireEvent.click(screen.getByRole("button", { name: /start autocode/i }));
    await advance(400);
    const log = screen.getByRole("log");
    expect(log).toHaveAttribute("aria-live", "polite");
  });

  it("prevents double-clicking START AUTOCODE", async () => {
    render(<SetupPage />);
    await advanceToStep3();
    fireEvent.click(screen.getByRole("radio", { name: /autonomous/i }));
    await advance(300);
    const startBtn = screen.getByRole("button", { name: /start autocode/i });
    fireEvent.click(startBtn);
    fireEvent.click(startBtn); // second click
    await advance(4400);
    // Should only log once
    const startCalls = logSpy.mock.calls.filter(
      (c) => c[0] === "[setup] starting first run"
    );
    expect(startCalls).toHaveLength(1);
  });

  it("uses review-only mode string in terminal for REVIEW ONLY", async () => {
    render(<SetupPage />);
    await advanceToStep3();
    fireEvent.click(screen.getByRole("radio", { name: /review only/i }));
    await advance(300);
    fireEvent.click(screen.getByRole("button", { name: /start autocode/i }));
    await advance(4400);
    expect(screen.getByText(/--mode review-only/)).toBeInTheDocument();
  });

  it("arrow down moves focus to next radio in mode group", async () => {
    render(<SetupPage />);
    await advanceToStep3();
    const autonomousRadio = screen.getByRole("radio", { name: /autonomous/i });
    const supervisedRadio = screen.getByRole("radio", { name: /supervised/i });
    autonomousRadio.focus();
    fireEvent.keyDown(autonomousRadio, { key: "ArrowDown" });
    expect(document.activeElement).toBe(supervisedRadio);
  });

  it("arrow up wraps from first to last radio", async () => {
    render(<SetupPage />);
    await advanceToStep3();
    const autonomousRadio = screen.getByRole("radio", { name: /autonomous/i });
    const reviewOnlyRadio = screen.getByRole("radio", { name: /review only/i });
    autonomousRadio.focus();
    fireEvent.keyDown(autonomousRadio, { key: "ArrowUp" });
    expect(document.activeElement).toBe(reviewOnlyRadio);
  });

  it("arrow down wraps from last to first radio", async () => {
    render(<SetupPage />);
    await advanceToStep3();
    const reviewOnlyRadio = screen.getByRole("radio", { name: /review only/i });
    const autonomousRadio = screen.getByRole("radio", { name: /autonomous/i });
    reviewOnlyRadio.focus();
    fireEvent.keyDown(reviewOnlyRadio, { key: "ArrowDown" });
    expect(document.activeElement).toBe(autonomousRadio);
  });

  it("renders main landmark", () => {
    render(<SetupPage />);
    expect(screen.getByRole("main")).toBeInTheDocument();
  });

  it("displays connected repo URL in success message", async () => {
    render(<SetupPage />);
    fireEvent.click(screen.getByRole("button", { name: /i've run this/i }));
    const repoInput = screen.getByLabelText(/paste your github repo url/i);
    fireEvent.change(repoInput, { target: { value: "https://github.com/acme/widget" } });
    fireEvent.click(screen.getByRole("button", { name: /^connect$/i }));
    await advance(1200);
    expect(screen.getByText(/github\.com\/acme\/widget/)).toBeInTheDocument();
  });

  it("disables connect button while connecting", () => {
    render(<SetupPage />);
    fireEvent.click(screen.getByRole("button", { name: /i've run this/i }));
    const repoInput = screen.getByLabelText(/paste your github repo url/i);
    fireEvent.change(repoInput, { target: { value: "https://github.com/user/repo" } });
    fireEvent.click(screen.getByRole("button", { name: /^connect$/i }));
    expect(screen.getByRole("button", { name: /connecting\.\.\./i })).toBeDisabled();
  });
});
