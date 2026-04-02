import type { Metadata } from 'next'
import PricingHero from '@/components/pricing/PricingHero'
import PricingTiers from '@/components/pricing/PricingTiers'
import PricingFaq from '@/components/pricing/PricingFaq'

export const metadata: Metadata = {
  title: 'Pricing — SuperPilot',
  description:
    'Simple, transparent pricing for every pack. Choose the plan that fits your dog and your life.',
}

function PawIcon() {
  return (
    <svg
      width="28"
      height="28"
      viewBox="0 0 28 28"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <ellipse cx="14" cy="17" rx="5.5" ry="5" className="fill-amber-400" />
      <ellipse cx="8.5" cy="11.5" rx="2.2" ry="2.8" className="fill-amber-400" />
      <ellipse cx="12" cy="9.5" rx="2.2" ry="2.8" className="fill-amber-400" />
      <ellipse cx="16" cy="9.5" rx="2.2" ry="2.8" className="fill-amber-400" />
      <ellipse cx="19.5" cy="11.5" rx="2.2" ry="2.8" className="fill-amber-400" />
    </svg>
  )
}

export default function PricingPage() {
  return (
    <div className="min-h-screen bg-slate-950 text-white font-sans">
      {/* Background decorations */}
      <div className="pointer-events-none fixed inset-0 overflow-hidden" aria-hidden="true">
        <div className="absolute -top-40 left-1/2 -translate-x-1/2 w-[900px] h-[600px] rounded-full bg-indigo-700/20 blur-3xl" />
        <div className="absolute top-1/3 -right-40 w-[500px] h-[500px] rounded-full bg-violet-700/15 blur-3xl" />
        <div className="absolute bottom-0 -left-40 w-[500px] h-[500px] rounded-full bg-indigo-900/20 blur-3xl" />
      </div>

      <div className="relative">
        <PricingHero />

        <PricingTiers />

        {/* ── Feature comparison callout ───────────────────────────────── */}
        <section
          aria-label="Plan comparison highlights"
          className="mx-auto max-w-4xl px-6 pb-24"
        >
          <div className="rounded-2xl border border-white/10 bg-white/5 p-8 sm:p-10">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-8">
              <div>
                <h2 className="text-xl font-semibold text-white">
                  Everything you need, nothing you don&apos;t
                </h2>
                <p className="mt-1 text-sm text-slate-400">
                  Every SuperPilot plan is built around your dog&apos;s wellbeing.
                </p>
              </div>
              <a
                href="/features"
                className="flex-shrink-0 text-sm font-medium text-indigo-400 hover:text-indigo-300 transition-colors"
              >
                See all features &rarr;
              </a>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
              {[
                {
                  icon: (
                    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                      <path d="M10 2C7.2 2 5 4.2 5 7C5 9.8 7.2 12 10 12C12.8 12 15 9.8 15 7C15 4.2 12.8 2 10 2ZM3 18C3 15.3 6.1 13 10 13C13.9 13 17 15.3 17 18H3Z" fill="#818cf8"/>
                    </svg>
                  ),
                  title: 'Dog-first profiles',
                  body: 'Store breed, age, weight, health history, vet contacts, and behavioral notes in one place.',
                },
                {
                  icon: (
                    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                      <path d="M10 1L12.5 7H19L13.5 11L15.5 18L10 14L4.5 18L6.5 11L1 7H7.5L10 1Z" fill="#818cf8"/>
                    </svg>
                  ),
                  title: 'AI-powered coaching',
                  body: "Personalized training plans that adapt to your dog's unique personality and learning pace.",
                },
                {
                  icon: (
                    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                      <path d="M10 2C8 2 6 3 5 4.5C4 6 4 8 5 10L10 18L15 10C16 8 16 6 15 4.5C14 3 12 2 10 2ZM10 11C8.3 11 7 9.7 7 8C7 6.3 8.3 5 10 5C11.7 5 13 6.3 13 8C13 9.7 11.7 11 10 11Z" fill="#818cf8"/>
                    </svg>
                  ),
                  title: 'GPS & activity tracking',
                  body: 'Track walks, runs, and off-leash play. Set daily activity goals and get trend reports over time.',
                },
              ].map((item) => (
                <div key={item.title} className="flex gap-4">
                  <div className="flex-shrink-0 mt-0.5 w-9 h-9 rounded-lg bg-indigo-500/15 flex items-center justify-center">
                    {item.icon}
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-white mb-1">{item.title}</h3>
                    <p className="text-xs leading-relaxed text-slate-400">{item.body}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        <PricingFaq />

        {/* ── CTA banner ───────────────────────────────────────────────── */}
        <section
          aria-label="Get started call to action"
          className="mx-auto max-w-6xl px-6 pb-24"
        >
          <div className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-indigo-600 via-violet-600 to-indigo-700 px-8 py-16 text-center sm:px-16">
            {/* Decorative circles */}
            <div
              className="pointer-events-none absolute -top-16 -left-16 w-64 h-64 rounded-full bg-white/5"
              aria-hidden="true"
            />
            <div
              className="pointer-events-none absolute -bottom-16 -right-16 w-80 h-80 rounded-full bg-white/5"
              aria-hidden="true"
            />

            <div className="relative">
              <div className="mb-4 flex justify-center">
                <PawIcon />
              </div>
              <h2 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
                Your dog deserves the best
              </h2>
              <p className="mt-4 text-lg text-indigo-200 max-w-lg mx-auto">
                Join over 50,000 dog owners who trust SuperPilot to keep their
                pups healthy, happy, and well-trained.
              </p>
              <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-4">
                <a
                  href="/signup"
                  className="w-full sm:w-auto rounded-xl bg-white px-8 py-3.5 text-sm font-semibold text-indigo-700 hover:bg-indigo-50 transition-colors shadow-lg shadow-indigo-900/30"
                >
                  Get started for free
                </a>
                <a
                  href="/demo"
                  className="w-full sm:w-auto rounded-xl border border-white/30 px-8 py-3.5 text-sm font-semibold text-white hover:bg-white/10 transition-colors"
                >
                  Watch a demo
                </a>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}
