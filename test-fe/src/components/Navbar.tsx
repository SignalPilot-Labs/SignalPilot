import Link from "next/link";

const navLinks = [
  { label: "Home", href: "/" },
  { label: "Partners", href: "/partners" },
  { label: "About", href: "/about" },
  { label: "Pricing", href: "/pricing" },
] as const;

export default function Navbar() {
  return (
    <header className="sticky top-0 z-50 w-full border-b border-white/10 bg-zinc-950/90 backdrop-blur-sm">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-6 px-4 sm:px-6 lg:px-8">
        {/* Logo */}
        <Link
          href="/"
          className="shrink-0 text-xl font-bold tracking-tight"
          aria-label="SuperPilot home"
        >
          <span className="bg-gradient-to-r from-indigo-400 to-violet-400 bg-clip-text text-transparent">
            SuperPilot
          </span>
        </Link>

        {/* Nav links — horizontal scroll on small screens */}
        <nav
          aria-label="Main navigation"
          className="flex flex-1 items-center overflow-x-auto [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        >
          <ul className="flex items-center gap-1">
            {navLinks.map(({ label, href }) => (
              <li key={href}>
                <Link
                  href={href}
                  className="whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium text-zinc-300 transition-colors duration-150 hover:bg-white/8 hover:text-white"
                >
                  {label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>

        {/* CTA */}
        <Link
          href="/get-started"
          className="shrink-0 rounded-md bg-amber-400 px-4 py-2 text-sm font-semibold text-zinc-900 transition-colors duration-150 hover:bg-amber-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-400"
        >
          Get Started
        </Link>
      </div>
    </header>
  );
}
