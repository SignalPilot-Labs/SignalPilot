import Link from "next/link";

const footerColumns = [
  {
    heading: "Product",
    links: [
      { label: "Features", href: "/features" },
      { label: "Pricing", href: "/pricing" },
      { label: "Demo", href: "/demo" },
    ],
  },
  {
    heading: "Company",
    links: [
      { label: "About", href: "/about" },
      { label: "Careers", href: "/careers" },
      { label: "Blog", href: "/blog" },
    ],
  },
  {
    heading: "Legal",
    links: [
      { label: "Privacy", href: "/privacy" },
      { label: "Terms", href: "/terms" },
    ],
  },
] as const;

function XIcon() {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="currentColor"
      aria-hidden="true"
      className="h-5 w-5"
    >
      <path d="M11.49 10.857 16.9 3.5h-1.278l-4.71 6.19L7.29 3.5H3l5.666 7.849L3 18.5h1.278l4.955-6.51L12.71 18.5H17l-5.51-7.643Z" />
    </svg>
  );
}

function GitHubIcon() {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="currentColor"
      aria-hidden="true"
      className="h-5 w-5"
    >
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M10 0C4.477 0 0 4.596 0 10.274c0 4.54 2.865 8.393 6.84 9.754.5.094.682-.221.682-.492 0-.243-.009-.886-.013-1.74-2.782.618-3.369-1.37-3.369-1.37-.454-1.183-1.11-1.498-1.11-1.498-.908-.635.069-.622.069-.622 1.003.072 1.531 1.055 1.531 1.055.891 1.565 2.338 1.113 2.908.851.09-.662.349-1.113.634-1.369-2.22-.258-4.555-1.136-4.555-5.056 0-1.116.39-2.03 1.029-2.746-.103-.258-.446-1.299.097-2.708 0 0 .84-.276 2.75 1.051A9.35 9.35 0 0 1 10 4.954a9.36 9.36 0 0 1 2.505.346c1.909-1.327 2.748-1.051 2.748-1.051.544 1.409.201 2.45.099 2.708.64.715 1.027 1.63 1.027 2.746 0 3.928-2.338 4.795-4.566 5.048.359.317.678.942.678 1.898 0 1.37-.012 2.475-.012 2.81 0 .273.18.59.688.49C17.138 18.663 20 14.812 20 10.274 20 4.596 15.523 0 10 0Z"
      />
    </svg>
  );
}

function LinkedInIcon() {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="currentColor"
      aria-hidden="true"
      className="h-5 w-5"
    >
      <path d="M4.477 2C3.108 2 2 3.116 2 4.493c0 1.377 1.108 2.494 2.477 2.494S6.955 5.87 6.955 4.493C6.955 3.116 5.845 2 4.477 2ZM2.18 7.87h4.594V18H2.18V7.87ZM7.909 7.87h4.4v1.388h.063c.612-1.18 2.11-2.423 4.344-2.423C20.865 6.835 22 9.576 22 13.472V18h-4.592v-3.838c0-1.64-.573-2.759-2.009-2.759-1.094 0-1.745.752-2.032 1.48-.104.258-.13.618-.13.978V18H8.649c.061-9.718 0-10.13-.74-10.13Z" />
    </svg>
  );
}

const socialLinks = [
  { label: "X (formerly Twitter)", href: "https://x.com", Icon: XIcon },
  { label: "GitHub", href: "https://github.com", Icon: GitHubIcon },
  { label: "LinkedIn", href: "https://linkedin.com", Icon: LinkedInIcon },
] as const;

export default function Footer() {
  return (
    <footer className="border-t border-white/10 bg-zinc-950">
      <div className="mx-auto max-w-7xl px-4 py-14 sm:px-6 lg:px-8">
        {/* Top section: branding + columns */}
        <div className="grid grid-cols-2 gap-10 sm:grid-cols-4">
          {/* Brand */}
          <div className="col-span-2 sm:col-span-1">
            <Link
              href="/"
              className="text-lg font-bold tracking-tight"
              aria-label="SuperPilot home"
            >
              <span className="bg-gradient-to-r from-indigo-400 to-violet-400 bg-clip-text text-transparent">
                SuperPilot
              </span>
            </Link>
            <p className="mt-3 max-w-[18rem] text-sm leading-6 text-zinc-400">
              AI-powered intelligence for every dog, every day.
            </p>

            {/* Social links */}
            <div className="mt-6 flex items-center gap-4">
              {socialLinks.map(({ label, href, Icon }) => (
                <a
                  key={href}
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={label}
                  className="text-zinc-500 transition-colors duration-150 hover:text-zinc-300"
                >
                  <Icon />
                </a>
              ))}
            </div>
          </div>

          {/* Link columns */}
          {footerColumns.map(({ heading, links }) => (
            <div key={heading}>
              <h3 className="text-xs font-semibold uppercase tracking-widest text-zinc-400">
                {heading}
              </h3>
              <ul className="mt-4 space-y-3">
                {links.map(({ label, href }) => (
                  <li key={href}>
                    <Link
                      href={href}
                      className="text-sm text-zinc-400 transition-colors duration-150 hover:text-white"
                    >
                      {label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        {/* Bottom bar */}
        <div className="mt-12 border-t border-white/10 pt-8">
          <p className="text-xs text-zinc-500">
            &copy; 2026 SuperPilot, Inc. All rights reserved.
          </p>
        </div>
      </div>
    </footer>
  );
}
