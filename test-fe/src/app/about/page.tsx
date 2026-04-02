import Link from "next/link";

const teamMembers = [
  {
    name: "Maya Osei",
    role: "Co-founder & CEO",
    initials: "MO",
    color: "bg-indigo-600",
    bio: "Former ML lead at Waymo. Maya believes the future of pet care is proactive, not reactive — and she built SuperPilot to prove it.",
  },
  {
    name: "Luca Ferreira",
    role: "Co-founder & CTO",
    initials: "LF",
    color: "bg-violet-600",
    bio: "Ex-staff engineer at Stripe. Luca architects the real-time data pipelines and AI inference infrastructure that make SuperPilot feel instant.",
  },
  {
    name: "Dr. Priya Nair",
    role: "Chief Veterinary Officer",
    initials: "PN",
    color: "bg-amber-500",
    bio: "Board-certified veterinary internist with 12 years of clinical practice. Priya ensures every recommendation SuperPilot makes meets the highest standard of care.",
  },
  {
    name: "Jordan Calloway",
    role: "Head of Product",
    initials: "JC",
    color: "bg-fuchsia-600",
    bio: "Previously led consumer product at Duolingo. Jordan obsesses over making complex health data feel simple and actionable for everyday dog owners.",
  },
];

const values = [
  {
    emoji: "🐾",
    title: "Dog-First, Always",
    description:
      "Every feature, every model, every design decision starts with one question: does this make a dog's life better? If the answer is anything but a clear yes, it doesn't ship.",
  },
  {
    emoji: "🔬",
    title: "Science Over Hype",
    description:
      "We partner only with evidence-based researchers and clinicians. Our AI recommendations are grounded in peer-reviewed veterinary literature and validated against real-world outcomes.",
  },
  {
    emoji: "🔒",
    title: "Privacy by Design",
    description:
      "Your dog's health data is yours. We use end-to-end encryption, minimal data retention, and never sell personal information to third parties — ever.",
  },
  {
    emoji: "🤝",
    title: "Open Ecosystem",
    description:
      "We believe the best outcome for dogs comes from collaboration, not lock-in. Our open partner platform lets best-in-class hardware and service providers plug in seamlessly.",
  },
];

const timeline = [
  {
    year: "2024",
    label: "Founded",
    description:
      "SuperPilot incorporated in San Francisco. Seed round of $4.2M led by Andreessen Horowitz Bio. First PawTech collar integration shipped to 500 beta testers.",
  },
  {
    year: "2025",
    label: "Series A",
    description:
      "$28M Series A led by General Catalyst. Launched the VetAI and DoggoHealth partnerships. Expanded the team to 40 people across engineering, veterinary science, and design.",
  },
  {
    year: "2026",
    label: "50k Users",
    description:
      "Crossed 50,000 active dogs on the platform. Launched BarkSmart integration. Named one of Fast Company's Most Innovative Companies in the Consumer Electronics category.",
  },
];

export default function AboutPage() {
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
            <Link href="/about" className="text-white font-medium">
              About
            </Link>
            <Link href="/partners" className="hover:text-white transition-colors">
              Partners
            </Link>
          </nav>
        </div>
      </header>

      {/* Hero */}
      <section className="mx-auto max-w-6xl px-6 pt-20 pb-16">
        <div className="inline-flex items-center gap-2 rounded-full border border-violet-500/30 bg-violet-500/10 px-4 py-1.5 text-xs font-medium text-violet-300 mb-6">
          Our Story
        </div>
        <h1 className="text-5xl font-bold tracking-tight text-white mb-6 max-w-2xl">
          About SuperPilot
        </h1>
        <p className="max-w-2xl text-lg text-zinc-400 leading-relaxed">
          SuperPilot is an AI-powered health and behaviour platform built for dogs and
          the people who love them. We connect smart devices, veterinary intelligence,
          nutrition science, and training technology into a single, seamless experience
          — so every dog gets the care they deserve, every single day.
        </p>
      </section>

      {/* Divider */}
      <div className="mx-auto max-w-6xl px-6">
        <div className="h-px bg-gradient-to-r from-transparent via-zinc-700 to-transparent" />
      </div>

      {/* Mission */}
      <section className="mx-auto max-w-6xl px-6 py-16">
        <div className="rounded-2xl border border-indigo-500/20 bg-indigo-950/30 p-10 lg:p-14">
          <p className="text-xs font-semibold uppercase tracking-widest text-indigo-400 mb-4">
            Mission
          </p>
          <blockquote className="text-2xl lg:text-3xl font-medium text-white leading-snug max-w-3xl">
            "To give every dog on Earth a longer, healthier, and happier life by making
            AI-powered veterinary intelligence accessible to every owner — regardless of
            income, location, or technical ability."
          </blockquote>
          <p className="mt-6 text-sm text-zinc-400">
            Dogs can't tell us when something is wrong. SuperPilot can.
          </p>
        </div>
      </section>

      {/* Team */}
      <section className="mx-auto max-w-6xl px-6 py-4 pb-16">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-zinc-500 mb-10">
          The Team
        </h2>
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {teamMembers.map((member) => (
            <div
              key={member.name}
              className="rounded-2xl border border-zinc-800 bg-zinc-900 p-6 hover:border-zinc-700 transition-colors"
            >
              <div
                className={`${member.color} flex h-12 w-12 items-center justify-center rounded-xl text-white text-sm font-bold mb-5 shadow-md`}
              >
                {member.initials}
              </div>
              <h3 className="text-base font-semibold text-white mb-0.5">
                {member.name}
              </h3>
              <p className="text-xs font-medium text-zinc-500 mb-3">{member.role}</p>
              <p className="text-sm text-zinc-400 leading-relaxed">{member.bio}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Divider */}
      <div className="mx-auto max-w-6xl px-6">
        <div className="h-px bg-gradient-to-r from-transparent via-zinc-700 to-transparent" />
      </div>

      {/* Values */}
      <section className="mx-auto max-w-6xl px-6 py-16">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-zinc-500 mb-10">
          Our Values
        </h2>
        <div className="grid gap-6 sm:grid-cols-2">
          {values.map((value) => (
            <div
              key={value.title}
              className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-7 hover:border-zinc-700 transition-colors"
            >
              <span className="text-3xl mb-4 block" role="img" aria-label={value.title}>
                {value.emoji}
              </span>
              <h3 className="text-base font-semibold text-white mb-2">{value.title}</h3>
              <p className="text-sm text-zinc-400 leading-relaxed">{value.description}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Divider */}
      <div className="mx-auto max-w-6xl px-6">
        <div className="h-px bg-gradient-to-r from-transparent via-zinc-700 to-transparent" />
      </div>

      {/* Timeline */}
      <section className="mx-auto max-w-6xl px-6 py-16">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-zinc-500 mb-10">
          Timeline
        </h2>
        <ol className="relative flex flex-col gap-0">
          {timeline.map((item, i) => (
            <li key={item.year} className="flex gap-8 pb-10 last:pb-0">
              {/* Spine */}
              <div className="flex flex-col items-center">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-white text-xs font-bold shadow-lg shadow-indigo-900/40">
                  {item.year.slice(2)}
                </div>
                {i < timeline.length - 1 && (
                  <div className="mt-2 flex-1 w-px bg-zinc-800" aria-hidden="true" />
                )}
              </div>
              {/* Content */}
              <div className="pb-2">
                <div className="flex items-baseline gap-3 mb-2">
                  <span className="text-lg font-bold text-white">{item.year}</span>
                  <span className="inline-flex items-center rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-0.5 text-xs font-medium text-amber-300">
                    {item.label}
                  </span>
                </div>
                <p className="text-sm text-zinc-400 leading-relaxed max-w-xl">
                  {item.description}
                </p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      {/* CTA */}
      <section className="border-t border-zinc-800">
        <div className="mx-auto max-w-6xl px-6 py-14 flex flex-col sm:flex-row items-center justify-between gap-6">
          <div>
            <h2 className="text-xl font-semibold text-white mb-1">
              Meet our partners
            </h2>
            <p className="text-sm text-zinc-400">
              The hardware, diagnostics, and training companies that power the SuperPilot ecosystem.
            </p>
          </div>
          <Link
            href="/partners"
            className="inline-flex items-center gap-2 rounded-full bg-indigo-600 px-6 py-3 text-sm font-semibold text-white hover:bg-indigo-500 transition-colors"
          >
            View Partners
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
      </section>

      {/* Footer */}
      <footer className="border-t border-zinc-800">
        <div className="mx-auto max-w-6xl px-6 py-8 flex flex-col sm:flex-row items-center justify-between gap-4 text-sm text-zinc-500">
          <span>© 2026 SuperPilot. All rights reserved.</span>
          <Link href="/partners" className="hover:text-zinc-300 transition-colors">
            Our Partners
          </Link>
        </div>
      </footer>
    </div>
  );
}
