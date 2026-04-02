'use client'

import { useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'

const NAV_LINKS = [
  { label: 'Home', href: '/' },
  { label: 'Partners', href: '/partners' },
  { label: 'About', href: '/about' },
  { label: 'Contact', href: '/contact' },
] as const

function PawIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 64 64"
      fill="currentColor"
      className="w-7 h-7"
      aria-hidden="true"
    >
      {/* Main pad */}
      <ellipse cx="32" cy="46" rx="14" ry="11" />
      {/* Toe pads */}
      <ellipse cx="14" cy="30" rx="6" ry="8" transform="rotate(-20 14 30)" />
      <ellipse cx="24" cy="22" rx="6" ry="8" transform="rotate(-5 24 22)" />
      <ellipse cx="40" cy="22" rx="6" ry="8" transform="rotate(5 40 22)" />
      <ellipse cx="50" cy="30" rx="6" ry="8" transform="rotate(20 50 30)" />
    </svg>
  )
}

function HamburgerIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      className="w-6 h-6"
      aria-hidden="true"
    >
      <line x1="3" y1="6" x2="21" y2="6" />
      <line x1="3" y1="12" x2="21" y2="12" />
      <line x1="3" y1="18" x2="21" y2="18" />
    </svg>
  )
}

function CloseIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      className="w-6 h-6"
      aria-hidden="true"
    >
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  )
}

export default function Navbar() {
  const [menuOpen, setMenuOpen] = useState(false)
  const pathname = usePathname()

  const toggleMenu = () => setMenuOpen((prev) => !prev)
  const closeMenu = () => setMenuOpen(false)

  return (
    <header className="sticky top-0 z-50 w-full" style={{ backgroundColor: '#1a1a2e' }}>
      <nav
        className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex items-center justify-between h-16"
        aria-label="Main navigation"
      >
        {/* Logo */}
        <Link
          href="/"
          className="flex items-center gap-2 text-white font-bold text-xl tracking-tight hover:opacity-90 transition-opacity"
          onClick={closeMenu}
        >
          <span style={{ color: '#6c5ce7' }}>
            <PawIcon />
          </span>
          <span>SuperPilot</span>
        </Link>

        {/* Desktop nav */}
        <ul className="hidden md:flex items-center gap-1 list-none m-0 p-0">
          {NAV_LINKS.map(({ label, href }) => {
            const isActive = pathname === href
            return (
              <li key={href}>
                <Link
                  href={href}
                  className={[
                    'px-4 py-2 rounded-md text-sm font-medium transition-colors duration-150',
                    isActive
                      ? 'text-white'
                      : 'text-gray-300 hover:text-white hover:bg-white/10',
                  ].join(' ')}
                  style={isActive ? { color: '#00cec9' } : undefined}
                  aria-current={isActive ? 'page' : undefined}
                >
                  {label}
                </Link>
              </li>
            )
          })}
        </ul>

        {/* Mobile hamburger */}
        <button
          type="button"
          onClick={toggleMenu}
          className="md:hidden text-gray-300 hover:text-white transition-colors p-2 rounded-md hover:bg-white/10"
          aria-expanded={menuOpen}
          aria-controls="mobile-menu"
          aria-label={menuOpen ? 'Close menu' : 'Open menu'}
        >
          {menuOpen ? <CloseIcon /> : <HamburgerIcon />}
        </button>
      </nav>

      {/* Mobile menu */}
      {menuOpen && (
        <div
          id="mobile-menu"
          className="md:hidden border-t border-white/10"
          style={{ backgroundColor: '#1a1a2e' }}
        >
          <ul className="flex flex-col gap-1 list-none m-0 px-4 py-3">
            {NAV_LINKS.map(({ label, href }) => {
              const isActive = pathname === href
              return (
                <li key={href}>
                  <Link
                    href={href}
                    onClick={closeMenu}
                    className={[
                      'block px-4 py-3 rounded-md text-sm font-medium transition-colors duration-150',
                      isActive
                        ? 'text-white bg-white/10'
                        : 'text-gray-300 hover:text-white hover:bg-white/10',
                    ].join(' ')}
                    style={isActive ? { color: '#00cec9' } : undefined}
                    aria-current={isActive ? 'page' : undefined}
                  >
                    {label}
                  </Link>
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </header>
  )
}
