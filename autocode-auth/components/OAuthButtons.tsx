"use client";

interface OAuthButtonsProps {
  onGitHub: () => void;
  onGoogle: () => void;
  disabled: boolean;
  githubLabel?: string;
  googleLabel?: string;
}

export default function OAuthButtons({
  onGitHub,
  onGoogle,
  disabled,
  githubLabel = "CONTINUE WITH GITHUB",
  googleLabel = "CONTINUE WITH GOOGLE",
}: OAuthButtonsProps) {
  return (
    <>
      <button
        onClick={onGitHub}
        disabled={disabled}
        className="w-full border-2 border-[var(--color-accent)] bg-transparent text-[var(--color-text)] font-bold text-sm uppercase tracking-[0.1em] py-4 px-6 cursor-pointer hover:bg-[var(--color-accent)] hover:text-[var(--color-bg)] disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {githubLabel}
      </button>

      <button
        onClick={onGoogle}
        disabled={disabled}
        className="w-full border-2 border-[var(--color-accent)] bg-transparent text-[var(--color-text)] font-bold text-sm uppercase tracking-[0.1em] py-4 px-6 cursor-pointer hover:bg-[var(--color-accent)] hover:text-[var(--color-bg)] disabled:opacity-50 disabled:cursor-not-allowed mt-4"
      >
        {googleLabel}
      </button>

      <div className="flex items-center gap-4 my-12">
        <div className="flex-1 h-[2px] bg-[var(--color-dim)]" />
        <span className="text-[var(--color-dim)] text-xs tracking-[0.15em] uppercase">OR</span>
        <div className="flex-1 h-[2px] bg-[var(--color-dim)]" />
      </div>
    </>
  );
}
