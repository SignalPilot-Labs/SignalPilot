"use client";

interface TextInputProps {
  id: string;
  type: "email" | "password" | "text";
  value: string;
  onChange: (value: string) => void;
  onBlur?: () => void;
  placeholder: string;
  autoComplete: string;
  disabled?: boolean;
  error?: string;
  errorId?: string;
}

export default function TextInput({
  id,
  type,
  value,
  onChange,
  onBlur,
  placeholder,
  autoComplete,
  disabled,
  error,
  errorId,
}: TextInputProps) {
  return (
    <div>
      <label htmlFor={id} className="sr-only">
        {placeholder.charAt(0) + placeholder.slice(1).toLowerCase()}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onBlur={onBlur}
        placeholder={placeholder}
        autoComplete={autoComplete}
        disabled={disabled}
        aria-describedby={error ? errorId : undefined}
        className="w-full bg-transparent border-0 border-b-2 border-[var(--color-border)] text-[var(--color-text)] font-mono text-sm tracking-[0.1em] py-3 placeholder:text-[var(--color-dim)] placeholder:uppercase focus-visible:border-[var(--color-accent)] outline-none focus-visible:outline-2 focus-visible:outline-[var(--color-accent)] focus-visible:outline-offset-2"
      />
      {error && (
        <p
          id={errorId}
          role="alert"
          className="text-[var(--color-error)] text-xs tracking-[0.1em] mt-2"
        >
          {error}
        </p>
      )}
    </div>
  );
}
