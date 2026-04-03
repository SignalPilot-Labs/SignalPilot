export interface AuthUser {
  name?: string | null;
  email?: string | null;
  image?: string | null;
}

export default function AuthHeader({ user }: { user?: AuthUser | null }) {
  return (
    <nav aria-label="Home" className="flex items-center justify-between mb-20">
      <a
        href="/"
        className="text-[13px] font-bold tracking-[0.15em] uppercase text-[var(--color-text)] hover:text-[var(--color-accent)]"
      >
        SIGNALPILOT AUTOCODE
      </a>
      {user && (
        <div className="flex items-center gap-3">
          {user.image && (
            <img
              src={user.image}
              alt={user.name || "User avatar"}
              width={24}
              height={24}
              className="border border-[var(--color-border)]"
            />
          )}
          <span className="text-[11px] text-[var(--color-dim)] tracking-[0.1em] uppercase">
            {user.name || user.email}
          </span>
          <form action="/api/auth/signout" method="post" className="inline">
            <button
              type="submit"
              className="text-[11px] text-[var(--color-dim)] tracking-[0.1em] uppercase hover:text-[var(--color-accent)] cursor-pointer bg-transparent border-0 p-0"
            >
              [SIGN OUT]
            </button>
          </form>
        </div>
      )}
    </nav>
  );
}
