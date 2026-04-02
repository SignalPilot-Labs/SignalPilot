import Link from "next/link";

const partners = [
  {
    slug: "pawtech",
    name: "PawTech",
    initials: "PT",
    color: "bg-indigo-600",
    tagline: "Smart Collars & Wearables",
    description:
      "PawTech builds next-generation smart collars packed with biometric sensors, GPS tracking, and real-time health monitoring — seamlessly synced with your SuperPilot dashboard.",
  },
  {
    slug: "vetai",
    name: "VetAI",
    initials: "VA",
    color: "bg-violet-600",
    tagline: "Veterinary Diagnostics",
    description:
      "VetAI brings clinical-grade AI diagnostics to your fingertips. From symptom analysis to lab result interpretation, VetAI helps SuperPilot surface actionable health insights before problems escalate.",
  },
  {
    slug: "doggohealth",
    name: "DoggoHealth",
    initials: "DH",
    color: "bg-amber-500",
    tagline: "Pet Nutrition & Wellness",
    description:
      "DoggoHealth formulates science-backed meal plans and supplement regimens tailored to each dog's breed, age, and activity level — powered by nutritional data flowing through SuperPilot.",
  },
  {
    slug: "barksmart",
    name: "BarkSmart",
    initials: "BS",
    color: "bg-fuchsia-600",
    tagline: "Intelligent Training Devices",
    description:
      "BarkSmart's adaptive training hardware uses positive-reinforcement algorithms and behavioral data from SuperPilot to craft personalised training programs that actually stick.",
  },
];

export default function PartnersPage() {
  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-50 font-sans">
      {/* Nav */}
      <header className="border-b border-zinc-800">
        <div className="mx-auto max-w-6xl px-6 py-4 flex items-center justify-between">
          <Link
            href="/"
            className="text-lg font-semibold tracking-tight text-white hover:text-indigo-400 transition-colors"
          >
            SuperPilot
          </Link>
          <nav className="flex gap-6 text-sm text-zinc-400">
            <Link href="/about" className="hover:text-white transition-colors">
              About
            </Link>
            <Link href="/partners" className="text-white font-medium">
              Partners
            </Link>
          </nav>
        </div>
      </header>

      {/* Hero */}
      <section className="mx-auto max-w-6xl px-6 pt-20 pb-14 text-center">
        <div className="inline-flex items-center gap-2 rounded-full border border-indigo-500/30 bg-indigo-500/10 px-4 py-1.5 text-xs font-medium text-indigo-300 mb-6">
          Ecosystem
        </div>
        <h1 className="text-5xl font-bold tracking-tight text-white mb-5">
          Our Partners
        </h1>
        <p className="mx-auto max-w-2xl text-lg text-zinc-400 leading-relaxed">
          SuperPilot is more than an app — it is a connected ecosystem of best-in-class
          hardware, diagnostics, nutrition, and training partners, all working in concert
          to give every dog the life they deserve.
        </p>
      </section>

      {/* Divider */}
      <div className="mx-auto max-w-6xl px-6">
        <div className="h-px bg-gradient-to-r from-transparent via-zinc-700 to-transparent" />
      </div>

      {/* Partner grid */}
      <section className="mx-auto max-w-6xl px-6 py-16">
        <div className="grid gap-6 sm:grid-cols-2">
          {partners.map((partner) => (
            <article
              key={partner.slug}
              className="group relative flex flex-col rounded-2xl border border-zinc-800 bg-zinc-900 p-8 hover:border-zinc-600 transition-colors duration-200"
            >
              {/* Subtle gradient glow on hover */}
              <div className="pointer-events-none absolute inset-0 rounded-2xl opacity-0 group-hover:opacity-100 transition-opacity duration-300 bg-gradient-to-br from-indigo-950/40 via-transparent to-transparent" />

              {/* Logo */}
              <div
                className={`${partner.color} flex h-14 w-14 items-center justify-center rounded-xl text-white text-lg font-bold tracking-wide mb-6 shadow-lg`}
              >
                {partner.initials}
              </div>

              {/* Content */}
              <div className="flex-1">
                <p className="text-xs font-semibold uppercase tracking-widest text-zinc-500 mb-1">
                  {partner.tagline}
                </p>
                <h2 className="text-xl font-semibold text-white mb-3">
                  {partner.name}
                </h2>
                <p className="text-sm text-zinc-400 leading-relaxed">
                  {partner.description}
                </p>
              </div>

              {/* CTA */}
              <div className="mt-8">
                <Link
                  href={`/partners/${partner.slug}`}
                  className="inline-flex items-center gap-2 text-sm font-medium text-indigo-400 hover:text-indigo-300 transition-colors"
                >
                  Learn More
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 16 16"
                    fill="currentColor"
                    className="h-4 w-4"
                    aria-hidden="true"
                  >
                    <path
                      fillRule="evenodd"
                      d="M6.22 4.22a.75.75 0 0 1 1.06 0l3.25 3.25a.75.75 0 0 1 0 1.06l-3.25 3.25a.75.75 0 0 1-1.06-1.06L9.19 8 6.22 5.28a.75.75 0 0 1 0-1.06Z"
                      clipRule="evenodd"
                    />
                  </svg>
                </Link>
              </div>
            </article>
          ))}
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-zinc-800 mt-8">
        <div className="mx-auto max-w-6xl px-6 py-8 flex flex-col sm:flex-row items-center justify-between gap-4 text-sm text-zinc-500">
          <span>© 2026 SuperPilot. All rights reserved.</span>
          <Link href="/about" className="hover:text-zinc-300 transition-colors">
            About SuperPilot
          </Link>
        </div>
      </footer>
    </div>
  );
}
