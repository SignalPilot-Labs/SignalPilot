import AuthLayout from "@/components/AuthLayout";

export default function NotFound() {
  return (
    <AuthLayout>
      <h1 className="text-[clamp(28px,5vw,40px)] font-bold uppercase tracking-[0.05em] mb-4">
        404
      </h1>

      <p className="text-sm uppercase tracking-[0.1em] text-[var(--color-dim)] mb-16">
        PAGE NOT FOUND
      </p>

      <a
        href="/"
        className="inline-block border-2 border-[var(--color-accent)] bg-transparent text-[var(--color-text)] font-bold text-sm uppercase tracking-[0.1em] py-3 px-6 hover:bg-[var(--color-accent)] hover:text-[var(--color-bg)]"
      >
        <span aria-hidden="true">← </span>BACK HOME
      </a>
    </AuthLayout>
  );
}
