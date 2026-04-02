import { PawPrint } from "./PawPrint";

export default function CtaSection() {
  return (
    <section
      id="signup"
      className="relative isolate overflow-hidden py-28 px-6"
      aria-labelledby="cta-heading"
    >
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 h-[600px] w-[600px] rounded-full bg-indigo-700/25 blur-[120px]" />
      </div>

      <div className="relative z-10 max-w-2xl mx-auto flex flex-col items-center gap-8 text-center">
        <div className="inline-flex items-center gap-2 rounded-full border border-amber-500/30 bg-amber-500/10 px-4 py-1.5 text-xs font-medium text-amber-300 uppercase tracking-widest">
          Limited Free Trials Available
        </div>

        <h2
          id="cta-heading"
          className="text-4xl sm:text-5xl font-extrabold tracking-tight text-white leading-tight"
        >
          Ready to transform{" "}
          <br className="hidden sm:block" />
          your dog&apos;s life?
        </h2>

        <p className="text-zinc-400 text-lg max-w-lg">
          Join tens of thousands of dog owners who have already unlocked the power of AI for their
          four-legged family members.
        </p>

        <form
          className="w-full flex flex-col sm:flex-row gap-3 max-w-md"
          aria-label="Email signup form"
        >
          <label htmlFor="email-signup" className="sr-only">
            Email address
          </label>
          <input
            id="email-signup"
            type="email"
            name="email"
            placeholder="Enter your email"
            autoComplete="email"
            required
            className="flex-1 rounded-full bg-white/5 border border-white/10 px-5 py-3.5 text-sm text-white placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-amber-400 focus:border-transparent transition-all"
          />
          <button
            type="submit"
            className="whitespace-nowrap bg-amber-400 text-zinc-900 font-bold px-6 py-3.5 rounded-full text-sm hover:bg-amber-300 transition-colors shadow-lg shadow-amber-500/20"
          >
            Start Free Trial
          </button>
        </form>

        <p className="text-zinc-500 text-sm">
          No credit card required &mdash; cancel anytime
        </p>
      </div>

      <PawPrint className="absolute bottom-8 right-12 w-20 h-20 text-indigo-500/5 rotate-12" />
      <PawPrint className="absolute top-10 left-10 w-12 h-12 text-violet-500/5 -rotate-12" />
    </section>
  );
}
