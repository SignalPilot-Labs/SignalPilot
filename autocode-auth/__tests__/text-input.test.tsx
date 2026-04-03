import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import TextInput from "@/components/TextInput";

describe("TextInput", () => {
  // 1. Renders input with correct type
  it("renders input with type='email'", () => {
    render(
      <TextInput
        id="email"
        type="email"
        value=""
        onChange={vi.fn()}
        placeholder="EMAIL"
        autoComplete="email"
      />
    );
    expect(screen.getByRole("textbox")).toHaveAttribute("type", "email");
  });

  it("renders input with type='password'", () => {
    const { container } = render(
      <TextInput
        id="password"
        type="password"
        value=""
        onChange={vi.fn()}
        placeholder="PASSWORD"
        autoComplete="current-password"
      />
    );
    expect(container.querySelector("input[type='password']")).toBeInTheDocument();
  });

  it("renders input with type='text'", () => {
    render(
      <TextInput
        id="username"
        type="text"
        value=""
        onChange={vi.fn()}
        placeholder="USERNAME"
        autoComplete="username"
      />
    );
    expect(screen.getByRole("textbox")).toHaveAttribute("type", "text");
  });

  // 2. Renders sr-only label derived from placeholder
  it("renders sr-only label with first char uppercase and rest lowercase from placeholder", () => {
    render(
      <TextInput
        id="email"
        type="email"
        value=""
        onChange={vi.fn()}
        placeholder="EMAIL"
        autoComplete="email"
      />
    );
    // "EMAIL" → first char "E" + "MAIL".toLowerCase() = "Email"
    expect(screen.getByText("Email")).toBeInTheDocument();
  });

  it("associates the sr-only label with the input via htmlFor", () => {
    render(
      <TextInput
        id="email"
        type="email"
        value=""
        onChange={vi.fn()}
        placeholder="EMAIL"
        autoComplete="email"
      />
    );
    const label = screen.getByText("Email");
    expect(label.tagName).toBe("LABEL");
    expect(label).toHaveAttribute("for", "email");
  });

  // 3. Input has correct autoComplete attribute
  it("sets autoComplete attribute on the input", () => {
    render(
      <TextInput
        id="email"
        type="email"
        value=""
        onChange={vi.fn()}
        placeholder="EMAIL"
        autoComplete="email"
      />
    );
    expect(screen.getByRole("textbox")).toHaveAttribute("autocomplete", "email");
  });

  // 4. Input has correct placeholder
  it("sets placeholder attribute on the input", () => {
    render(
      <TextInput
        id="email"
        type="email"
        value=""
        onChange={vi.fn()}
        placeholder="EMAIL"
        autoComplete="email"
      />
    );
    expect(screen.getByRole("textbox")).toHaveAttribute("placeholder", "EMAIL");
  });

  // 5. Calls onChange with the new value when typed
  it("calls onChange with the new value when the user types", () => {
    const onChange = vi.fn();
    render(
      <TextInput
        id="email"
        type="email"
        value=""
        onChange={onChange}
        placeholder="EMAIL"
        autoComplete="email"
      />
    );
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "user@example.com" } });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("user@example.com");
  });

  // 6. Calls onBlur when input loses focus
  it("calls onBlur when the input loses focus", () => {
    const onBlur = vi.fn();
    render(
      <TextInput
        id="email"
        type="email"
        value=""
        onChange={vi.fn()}
        onBlur={onBlur}
        placeholder="EMAIL"
        autoComplete="email"
      />
    );
    fireEvent.blur(screen.getByRole("textbox"));
    expect(onBlur).toHaveBeenCalledTimes(1);
  });

  it("does not throw when onBlur is not provided and input loses focus", () => {
    render(
      <TextInput
        id="email"
        type="email"
        value=""
        onChange={vi.fn()}
        placeholder="EMAIL"
        autoComplete="email"
      />
    );
    expect(() => fireEvent.blur(screen.getByRole("textbox"))).not.toThrow();
  });

  // 7. Shows error message when error prop is set
  it("renders error message when error prop is provided", () => {
    render(
      <TextInput
        id="email"
        type="email"
        value=""
        onChange={vi.fn()}
        placeholder="EMAIL"
        autoComplete="email"
        error="Invalid email address"
        errorId="email-error"
      />
    );
    expect(screen.getByText("Invalid email address")).toBeInTheDocument();
  });

  // 8. Does not show error when error is empty string
  it("does not render error element when error is empty string", () => {
    render(
      <TextInput
        id="email"
        type="email"
        value=""
        onChange={vi.fn()}
        placeholder="EMAIL"
        autoComplete="email"
        error=""
        errorId="email-error"
      />
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  // 9. Error element has role="alert"
  it("error element has role='alert'", () => {
    render(
      <TextInput
        id="email"
        type="email"
        value=""
        onChange={vi.fn()}
        placeholder="EMAIL"
        autoComplete="email"
        error="Required field"
        errorId="email-error"
      />
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Required field");
  });

  // 10. Input has aria-describedby pointing to errorId when error exists
  it("sets aria-describedby to errorId when error is present", () => {
    render(
      <TextInput
        id="email"
        type="email"
        value=""
        onChange={vi.fn()}
        placeholder="EMAIL"
        autoComplete="email"
        error="Invalid email address"
        errorId="email-error"
      />
    );
    expect(screen.getByRole("textbox")).toHaveAttribute("aria-describedby", "email-error");
  });

  // 11. Input does not have aria-describedby when no error
  it("does not set aria-describedby when error is absent", () => {
    render(
      <TextInput
        id="email"
        type="email"
        value=""
        onChange={vi.fn()}
        placeholder="EMAIL"
        autoComplete="email"
        errorId="email-error"
      />
    );
    expect(screen.getByRole("textbox")).not.toHaveAttribute("aria-describedby");
  });

  it("does not set aria-describedby when error is empty string", () => {
    render(
      <TextInput
        id="email"
        type="email"
        value=""
        onChange={vi.fn()}
        placeholder="EMAIL"
        autoComplete="email"
        error=""
        errorId="email-error"
      />
    );
    expect(screen.getByRole("textbox")).not.toHaveAttribute("aria-describedby");
  });

  // 12. Input is disabled when disabled=true
  it("disables the input when disabled=true", () => {
    render(
      <TextInput
        id="email"
        type="email"
        value=""
        onChange={vi.fn()}
        placeholder="EMAIL"
        autoComplete="email"
        disabled={true}
      />
    );
    expect(screen.getByRole("textbox")).toBeDisabled();
  });

  it("does not disable the input when disabled is omitted", () => {
    render(
      <TextInput
        id="email"
        type="email"
        value=""
        onChange={vi.fn()}
        placeholder="EMAIL"
        autoComplete="email"
      />
    );
    expect(screen.getByRole("textbox")).not.toBeDisabled();
  });
});
