import type { Metadata } from 'next'
import FaqAccordion from '@/components/FaqAccordion'

export const metadata: Metadata = {
  title: 'Pricing — SuperPilot',
  description:
    'Simple, transparent pricing for every pack. Choose the plan that fits your dog and your life.',
}

// ─── Types ────────────────────────────────────────────────────────────────────

interface Feature {
  text: string
}

interface PricingTier {
  name: string
  price: string
  period: string
  description: string
  features: Feature[]
  cta: string
  href: string
  highlighted: boolean
  badge?: string
}

interface FaqItem {
  question: string
  answer: string
}

// ─── Data ─────────────────────────────────────────────────────────────────────

const tiers: PricingTier[] = [
  {
    name: 'Puppy Plan',
    price: 'Free',
    period: 'forever',
    description:
      'Everything you need to get started on the path to a happier, healthier dog.',
    features: [
      { text: '1 dog profile' },
      { text: 'Basic activity tracking' },
      { text: 'Community access' },
      { text: 'Weekly health tips' },
    ],
    cta: 'Get Started Free',
    href: '/signup',
    highlighted: false,
  },
  {
    name: 'Good Boy Plan',
    price: '$9.99',
    period: 'per month',
    description:
      'AI-powered coaching and health tools for dogs who deserve the very best.',
    features: [
      { text: 'Up to 3 dog profiles' },
      { text: 'AI training coach' },
      { text: 'Health monitoring' },
      { text: 'GPS activity tracking' },
      { text: 'Priority support' },
    ],
    cta: 'Start Free Trial',
    href: '/signup?plan=good-boy',
    highlighted: true,
    badge: 'Most Popular',
  },
  {
    name: 'Alpha Pack',
    price: '$24.99',
    period: 'per month',
    description:
      'Enterprise-grade tools for serious breeders, trainers, and multi-dog households.',
    features: [
      { text: 'Unlimited dog profiles' },
      { text: 'Advanced AI behavior analysis' },
      { text: 'Vet telehealth integration' },
      { text: 'Custom training programs' },
      { text: 'Dedicated account manager' },
      { text: 'API access' },
    ],
    cta: 'Contact Sales',
    href: '/contact',
    highlighted: false,
  },
]

const faqs: FaqItem[] = [
  {
    question: 'Can I change my plan at any time?',
    answer:
      'Yes. You can upgrade, downgrade, or cancel your subscription at any time from your account settings. When upgrading, the change takes effect immediately and you are billed the prorated difference. When downgrading, the change takes effect at the end of your current billing period.',
  },
  {
    question: 'Is there a free trial for paid plans?',
    answer:
      'The Good Boy Plan includes a 14-day free trial — no credit card required. If you decide it is not right for you, simply cancel before the trial ends and you will never be charged. The Alpha Pack plan offers a personalized demo; contact our sales team to get started.',
  },
  {
    question: 'What happens to my data if I cancel?',
    answer:
      'Your dog profiles, activity history, and training records are retained for 30 days after cancellation, giving you time to export everything. After 30 days, data is permanently deleted in accordance with our privacy policy.',
  },
  {
    question: 'Do you offer discounts for annual billing?',
    answer:
      'Yes. Choosing annual billing saves you two months compared to monthly — effectively giving you 12 months for the price of 10. Annual plans are available for both the Good Boy and Alpha Pack tiers and can be selected during signup or from your account settings.',
  },
  {
    question: 'Can I add more dogs beyond my plan limit?',
    answer:
      'On the Good Boy Plan you can have up to 3 dog profiles. If your pack keeps growing, upgrading to Alpha Pack gives you unlimited profiles. You can also temporarily add an extra profile by contacting support, and we will work out the best option for your situation.',
  },
]

// ─── Sub-components ───────────────────────────────────────────────────────────

function CheckIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      className="flex-shrink-0 mt-0.5"
    >
      <circle cx="8" cy="8" r="8" className="fill-indigo-500/20" />
      <path
        d="M4.5 8L7 10.5L11.5 5.5"
        stroke="#818cf8"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
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
      {/* Main pad */}
      <ellipse cx="14" cy="17" rx="5.5" ry="5" className="fill-amber-400" />
      {/* Toes */}
      <ellipse cx="8.5" cy="11.5" rx="2.2" ry="2.8" className="fill-amber-400" />
      <ellipse cx="12" cy="9.5" rx="2.2" ry="2.8" className="fill-amber-400" />
      <ellipse cx="16" cy="9.5" rx="2.2" ry="2.8" className="fill-amber-400" />
      <ellipse cx="19.5" cy="11.5" rx="2.2" ry="2.8" className="fill-amber-400" />
    </svg>
  )
}

function TierCard({ tier }: { tier: PricingTier }) {
  const { highlighted } = tier

  return (
    <article
      aria-label={`${tier.name} pricing tier`}
      className={[
        'relative flex flex-col rounded-2xl p-8 transition-shadow',
        highlighted
          ? 'bg-gradient-to-b from-indigo-600 to-violet-700 ring-2 ring-indigo-400 shadow-2xl shadow-indigo-900/50 scale-[1.03] z-10'
          : 'bg-white/5 border border-white/10 hover:border-white/20 hover:bg-white/[0.07]',
      ].join(' ')}
    >
      {/* Badge */}
      {tier.badge && (
        <div className="absolute -top-3.5 left-1/2 -translate-x-1/2">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-400 px-3.5 py-1 text-xs font-semibold uppercase tracking-wide text-amber-900">
            <PawIcon />
            {tier.badge}
          </span>
        </div>
      )}

      {/* Header */}
      <header className="mb-6">
        <h2
          className={`text-sm font-semibold uppercase tracking-widest mb-3 ${highlighted ? 'text-indigo-200' : 'text-indigo-400'}`}
        >
          {tier.name}
        </h2>

        <div className="flex items-end gap-1.5 mb-3">
          <span
            className={`text-4xl font-bold tracking-tight ${highlighted ? 'text-white' : 'text-white'}`}
          >
            {tier.price}
          </span>
          {tier.price !== 'Free' && (
            <span
              className={`mb-1 text-sm ${highlighted ? 'text-indigo-200' : 'text-slate-400'}`}
            >
              / mo
            </span>
          )}
        </div>

        <p
          className={`text-sm leading-relaxed ${highlighted ? 'text-indigo-100' : 'text-slate-400'}`}
        >
          {tier.description}
        </p>
      </header>

      {/* Divider */}
      <hr
        className={`mb-6 border-t ${highlighted ? 'border-indigo-500/50' : 'border-white/10'}`}
      />

      {/* Features */}
      <ul className="mb-8 flex flex-col gap-3" role="list">
        {tier.features.map((feature) => (
          <li key={feature.text} className="flex items-start gap-3">
            <CheckIcon />
            <span
              className={`text-sm ${highlighted ? 'text-indigo-50' : 'text-slate-300'}`}
            >
              {feature.text}
            </span>
          </li>
        ))}
      </ul>

      {/* CTA */}
      <div className="mt-auto">
        <a
          href={tier.href}
          className={[
            'block w-full rounded-xl px-6 py-3.5 text-center text-sm font-semibold transition-all duration-150',
            highlighted
              ? 'bg-white text-indigo-700 hover:bg-indigo-50 shadow-lg shadow-indigo-900/30'
              : 'bg-indigo-600/20 text-indigo-300 border border-indigo-500/30 hover:bg-indigo-600/30 hover:border-indigo-400/50 hover:text-white',
          ].join(' ')}
        >
          {tier.cta}
        </a>
      </div>
    </article>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

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
        {/* ── Hero ─────────────────────────────────────────────────────── */}
        <header className="mx-auto max-w-3xl px-6 pt-20 pb-16 text-center">
          {/* Eyebrow */}
          <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-indigo-500/30 bg-indigo-500/10 px-4 py-1.5 text-sm font-medium text-indigo-300">
            <PawIcon />
            <span>Simple, Transparent Pricing</span>
          </div>

          <h1 className="text-5xl font-bold tracking-tight text-white sm:text-6xl">
            The right plan for{' '}
            <span className="relative inline-block">
              <span className="relative z-10 bg-gradient-to-r from-indigo-400 via-violet-400 to-amber-400 bg-clip-text text-transparent">
                every good dog
              </span>
              <span
                aria-hidden="true"
                className="absolute inset-x-0 bottom-1 h-3 bg-amber-400/15 blur-sm rounded"
              />
            </span>
          </h1>

          <p className="mt-6 text-lg leading-relaxed text-slate-400 max-w-xl mx-auto">
            Start free and upgrade as your pack grows. No hidden fees, no
            lock-in — just smarter tools to help your dog thrive.
          </p>

          {/* Social proof */}
          <div className="mt-10 flex flex-wrap items-center justify-center gap-6 text-sm text-slate-500">
            <div className="flex items-center gap-2">
              <div className="flex -space-x-1.5">
                {['bg-indigo-400', 'bg-violet-400', 'bg-amber-400', 'bg-pink-400'].map(
                  (color) => (
                    <div
                      key={color}
                      className={`w-6 h-6 rounded-full border-2 border-slate-950 ${color}`}
                      aria-hidden="true"
                    />
                  )
                )}
              </div>
              <span>50,000+ happy owners</span>
            </div>
            <div className="hidden sm:block w-px h-4 bg-slate-700" aria-hidden="true" />
            <div className="flex items-center gap-1.5">
              {/* Stars */}
              <div className="flex gap-0.5" aria-label="4.9 out of 5 stars">
                {Array.from({ length: 5 }).map((_, i) => (
                  <svg
                    key={i}
                    width="14"
                    height="14"
                    viewBox="0 0 14 14"
                    fill="none"
                    xmlns="http://www.w3.org/2000/svg"
                    aria-hidden="true"
                  >
                    <path
                      d="M7 1L8.545 5.09H13L9.59 7.59L10.91 12L7 9.5L3.09 12L4.41 7.59L1 5.09H5.455L7 1Z"
                      fill="#fbbf24"
                    />
                  </svg>
                ))}
              </div>
              <span>4.9 / 5 on the App Store</span>
            </div>
            <div className="hidden sm:block w-px h-4 bg-slate-700" aria-hidden="true" />
            <span>14-day free trial</span>
          </div>
        </header>

        {/* ── Pricing grid ─────────────────────────────────────────────── */}
        <section aria-label="Pricing tiers" className="mx-auto max-w-6xl px-6 pb-24">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-start">
            {tiers.map((tier) => (
              <TierCard key={tier.name} tier={tier} />
            ))}
          </div>

          {/* Fine print */}
          <p className="mt-10 text-center text-sm text-slate-500">
            All plans include a 14-day free trial. No credit card required to
            get started.{' '}
            <a
              href="/terms"
              className="text-indigo-400 underline underline-offset-2 hover:text-indigo-300 transition-colors"
            >
              View full terms
            </a>
            .
          </p>
        </section>

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
                  body: 'Personalized training plans that adapt to your dog\'s unique personality and learning pace.',
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

        {/* ── FAQ ──────────────────────────────────────────────────────── */}
        <section
          aria-labelledby="faq-heading"
          className="mx-auto max-w-3xl px-6 pb-32"
        >
          <div className="text-center mb-12">
            <h2
              id="faq-heading"
              className="text-3xl font-bold tracking-tight text-white"
            >
              Frequently asked questions
            </h2>
            <p className="mt-3 text-slate-400">
              Can&apos;t find the answer you&apos;re looking for?{' '}
              <a
                href="/contact"
                className="text-indigo-400 underline underline-offset-2 hover:text-indigo-300 transition-colors"
              >
                Reach out to our team
              </a>
              .
            </p>
          </div>

          <FaqAccordion items={faqs} />
        </section>

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
