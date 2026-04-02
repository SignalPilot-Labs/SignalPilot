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

export default function PricingHero() {
  return (
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
  )
}
