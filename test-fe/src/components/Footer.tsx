import Link from 'next/link'

const COMPANY_LINKS = [
  { label: 'About Us', href: '/about' },
  { label: 'Partners', href: '/partners' },
  { label: 'Careers', href: '#' },
  { label: 'Press', href: '#' },
  { label: 'Blog', href: '#' },
]

const PRODUCT_LINKS = [
  { label: 'Features', href: '#' },
  { label: 'Pricing', href: '#' },
  { label: 'Integrations', href: '#' },
  { label: 'Changelog', href: '#' },
  { label: 'Roadmap', href: '#' },
]

interface SocialIconProps {
  path: string
  label: string
}

function SocialIcon({ path, label }: SocialIconProps) {
  return (
    <a
      href="#"
      aria-label={label}
      className="text-gray-400 hover:text-white transition-colors duration-150"
    >
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 24 24"
        fill="currentColor"
        className="w-5 h-5"
        aria-hidden="true"
      >
        <path d={path} />
      </svg>
    </a>
  )
}

function PawIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 64 64"
      fill="currentColor"
      className="w-6 h-6"
      aria-hidden="true"
    >
      <ellipse cx="32" cy="46" rx="14" ry="11" />
      <ellipse cx="14" cy="30" rx="6" ry="8" transform="rotate(-20 14 30)" />
      <ellipse cx="24" cy="22" rx="6" ry="8" transform="rotate(-5 24 22)" />
      <ellipse cx="40" cy="22" rx="6" ry="8" transform="rotate(5 40 22)" />
      <ellipse cx="50" cy="30" rx="6" ry="8" transform="rotate(20 50 30)" />
    </svg>
  )
}

// Twitter/X path
const TWITTER_PATH =
  'M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.748l7.73-8.835L1.254 2.25H8.08l4.259 5.63zm-1.161 17.52h1.833L7.084 4.126H5.117z'

// GitHub path
const GITHUB_PATH =
  'M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0 1 12 6.844a9.59 9.59 0 0 1 2.504.337c1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.02 10.02 0 0 0 22 12.017C22 6.484 17.522 2 12 2z'

// LinkedIn path
const LINKEDIN_PATH =
  'M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 0 1-2.063-2.065 2.064 2.064 0 1 1 2.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z'

export default function Footer() {
  const currentYear = new Date().getFullYear()

  return (
    <footer style={{ backgroundColor: '#1a1a2e' }} className="text-gray-300">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-14">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-10">

          {/* Column 1 — Company */}
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-500 mb-4">
              Company
            </h3>
            <ul className="space-y-3 list-none m-0 p-0">
              {COMPANY_LINKS.map(({ label, href }) => (
                <li key={label}>
                  <Link
                    href={href}
                    className="text-sm text-gray-400 hover:text-white transition-colors duration-150"
                  >
                    {label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>

          {/* Column 2 — Product */}
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-500 mb-4">
              Product
            </h3>
            <ul className="space-y-3 list-none m-0 p-0">
              {PRODUCT_LINKS.map(({ label, href }) => (
                <li key={label}>
                  <Link
                    href={href}
                    className="text-sm text-gray-400 hover:text-white transition-colors duration-150"
                  >
                    {label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>

          {/* Column 3 — Contact */}
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-500 mb-4">
              Contact
            </h3>
            <ul className="space-y-3 list-none m-0 p-0 text-sm text-gray-400">
              <li>
                <Link
                  href="/contact"
                  className="hover:text-white transition-colors duration-150"
                >
                  Get in touch
                </Link>
              </li>
              <li>
                <a
                  href="mailto:hello@superpilot.ai"
                  className="hover:text-white transition-colors duration-150"
                >
                  hello@superpilot.ai
                </a>
              </li>
              <li className="pt-1">
                <address className="not-italic leading-relaxed text-gray-500">
                  123 Bark Avenue
                  <br />
                  San Francisco, CA 94102
                </address>
              </li>
            </ul>
          </div>
        </div>

        {/* Divider */}
        <div className="mt-12 pt-8 border-t border-white/10 flex flex-col sm:flex-row items-center justify-between gap-6">
          {/* Brand */}
          <div className="flex items-center gap-2">
            <span style={{ color: '#6c5ce7' }}>
              <PawIcon />
            </span>
            <span className="font-bold text-white tracking-tight">SuperPilot</span>
            <span className="text-gray-500 text-sm ml-2">
              AI-Powered Intelligence for Your Best Friend.
            </span>
          </div>

          {/* Social links */}
          <div className="flex items-center gap-4">
            <SocialIcon path={TWITTER_PATH} label="SuperPilot on X (Twitter)" />
            <SocialIcon path={GITHUB_PATH} label="SuperPilot on GitHub" />
            <SocialIcon path={LINKEDIN_PATH} label="SuperPilot on LinkedIn" />
          </div>
        </div>

        {/* Copyright */}
        <p className="mt-6 text-center text-xs text-gray-600">
          &copy; {currentYear} SuperPilot, Inc. All rights reserved.
        </p>
      </div>
    </footer>
  )
}
