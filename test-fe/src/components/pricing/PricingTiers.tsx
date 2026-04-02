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
      <ellipse cx="14" cy="17" rx="5.5" ry="5" className="fill-amber-400" />
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

export default function PricingTiers() {
  return (
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
  )
}
