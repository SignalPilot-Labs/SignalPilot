import Link from "next/link";

// --- SVG Icons ---

function BrainIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="28"
      height="28"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z" />
      <path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z" />
      <path d="M15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4" />
      <path d="M17.599 6.5a3 3 0 0 0 .399-1.375" />
      <path d="M6.003 5.125A3 3 0 0 0 6.401 6.5" />
      <path d="M3.477 10.896a4 4 0 0 1 .585-.396" />
      <path d="M19.938 10.5a4 4 0 0 1 .585.396" />
      <path d="M6 18a4 4 0 0 1-1.967-.516" />
      <path d="M19.967 17.484A4 4 0 0 1 18 18" />
    </svg>
  );
}

function HeartPulseIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="28"
      height="28"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z" />
      <path d="M3.22 12H9.5l1.5-3 2 4.5 1.5-3 1.5 3h5.27" />
    </svg>
  );
}

function MapPinIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="28"
      height="28"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z" />
      <circle cx="12" cy="10" r="3" />
    </svg>
  );
}

function EyeIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="28"
      height="28"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function StarIcon({ filled = true }: { filled?: boolean }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill={filled ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
    </svg>
  );
}

function ArrowRightIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M5 12h14" />
      <path d="m12 5 7 7-7 7" />
    </svg>
  );
}

function PlayIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
    >
      <polygon points="5 3 19 12 5 21 5 3" />
    </svg>
  );
}

// --- Data ---

const features = [
  {
    icon: <BrainIcon />,
    title: "AI Training Coach",
    description:
      "Personalized training plans built around your dog's breed, age, and temperament. Real-time feedback adapts each session for faster, lasting results.",
    accent: "from-violet-500 to-indigo-500",
    bg: "bg-violet-500/10",
    border: "border-violet-500/20",
    text: "text-violet-400",
  },
  {
    icon: <HeartPulseIcon />,
    title: "Health Monitor",
    description:
      "Track vitals, spot anomalies early, and receive AI-driven alerts before small issues become serious. Integrated with leading vet platforms.",
    accent: "from-rose-500 to-pink-500",
    bg: "bg-rose-500/10",
    border: "border-rose-500/20",
    text: "text-rose-400",
  },
  {
    icon: <MapPinIcon />,
    title: "Activity Tracker",
    description:
      "GPS-powered walk mapping, daily exercise goals, and breed-specific activity benchmarks. Keep your dog fit and your mind at ease.",
    accent: "from-amber-500 to-orange-500",
    bg: "bg-amber-500/10",
    border: "border-amber-500/20",
    text: "text-amber-400",
  },
  {
    icon: <EyeIcon />,
    title: "Behavior Analysis",
    description:
      "Understand your dog's moods and emotional patterns through continuous AI observation. Decode barks, body language, and behavioral shifts.",
    accent: "from-teal-500 to-cyan-500",
    bg: "bg-teal-500/10",
    border: "border-teal-500/20",
    text: "text-teal-400",
  },
];

const testimonials = [
  {
    name: "Sarah Mitchell",
    dog: "Golden Retriever, 3 yrs",
    quote:
      "The AI training coach is like having a professional dog trainer in my pocket. Buddy went from pulling on the leash to walking perfectly in just two weeks.",
    initials: "SM",
    avatarBg: "bg-violet-500",
  },
  {
    name: "James Okafor",
    dog: "French Bulldog, 2 yrs",
    quote:
      "The health monitor caught an irregular breathing pattern I had no idea about. My vet confirmed it early. SuperPilot literally helped save Biscuit's life.",
    initials: "JO",
    avatarBg: "bg-indigo-500",
  },
  {
    name: "Priya Nair",
    dog: "Border Collie, 4 yrs",
    quote:
      "Luna is high-energy and I struggled to keep up. The activity tracker sets the perfect goals for her breed and she's never been happier or calmer at home.",
    initials: "PN",
    avatarBg: "bg-pink-500",
  },
];

const partners = [
  { name: "PawTech", tagline: "Smart pet hardware" },
  { name: "VetAI", tagline: "AI veterinary diagnostics" },
  { name: "DoggoHealth", tagline: "Canine wellness data" },
  { name: "BarkSmart", tagline: "Behavioral science" },
];

// --- Decorative background shape ---

function HeroBlob() {
  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden">
      <div className="absolute -top-40 left-1/2 -translate-x-1/2 h-[700px] w-[700px] rounded-full bg-indigo-600/30 blur-[120px]" />
      <div className="absolute top-20 left-1/4 h-[400px] w-[400px] rounded-full bg-violet-600/20 blur-[100px]" />
      <div className="absolute top-10 right-1/4 h-[300px] w-[300px] rounded-full bg-purple-500/20 blur-[80px]" />
      <div
        className="absolute inset-0 opacity-[0.03]"
        style={{
          backgroundImage:
            "linear-gradient(rgb(255 255 255 / 0.5) 1px, transparent 1px), linear-gradient(90deg, rgb(255 255 255 / 0.5) 1px, transparent 1px)",
          backgroundSize: "60px 60px",
        }}
      />
    </div>
  );
}

// --- Decorative paw print SVG ---

function PawPrint({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 64 64"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden="true"
    >
      <ellipse cx="20" cy="14" rx="5" ry="7" />
      <ellipse cx="44" cy="14" rx="5" ry="7" />
      <ellipse cx="10" cy="30" rx="4" ry="6" />
      <ellipse cx="54" cy="30" rx="4" ry="6" />
      <path d="M32 22c-10 0-18 8-14 20 2 6 6 10 10 12 2 1 4 1 8 0 4-2 8-6 10-12 4-12-4-20-14-20z" />
    </svg>
  );
}

// --- Star Rating ---

function StarRating({ count = 5 }: { count?: number }) {
  return (
    <div className="flex gap-0.5 text-amber-400" role="img" aria-label={`${count} out of 5 stars`}>
      {Array.from({ length: 5 }, (_, i) => (
        <StarIcon key={i} filled={i < count} />
      ))}
    </div>
  );
}

// --- Page ---

export default function Home() {
  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 font-sans">

      {/* Nav */}
      <header className="relative z-20 flex items-center justify-between px-6 py-5 max-w-7xl mx-auto">
        <div className="flex items-center gap-2">
          <PawPrint className="w-7 h-7 text-amber-400" />
          <span className="text-xl font-bold tracking-tight text-white">
            Super<span className="text-amber-400">Pilot</span>
          </span>
        </div>
        <nav className="hidden md:flex items-center gap-8 text-sm text-zinc-400">
          <a href="#features" className="hover:text-white transition-colors">Features</a>
          <a href="#testimonials" className="hover:text-white transition-colors">Reviews</a>
          <Link href="/partners" className="hover:text-white transition-colors">Partners</Link>
        </nav>
        <a
          href="#signup"
          className="text-sm font-semibold bg-amber-400 text-zinc-900 px-4 py-2 rounded-full hover:bg-amber-300 transition-colors"
        >
          Get Started
        </a>
      </header>

      <main>

        {/* Hero */}
        <section
          className="relative isolate overflow-hidden pt-16 pb-28 px-6"
          aria-labelledby="hero-headline"
        >
          <HeroBlob />

          <div className="relative z-10 max-w-4xl mx-auto text-center flex flex-col items-center gap-8">
            <div className="inline-flex items-center gap-2 rounded-full border border-indigo-500/40 bg-indigo-500/10 px-4 py-1.5 text-xs font-medium text-indigo-300 uppercase tracking-widest">
              <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse" />
              AI-Powered Dog Care
            </div>

            <h1
              id="hero-headline"
              className="text-5xl sm:text-6xl md:text-7xl font-extrabold tracking-tight leading-[1.05] text-white"
            >
              Your Dog&apos;s{" "}
              <span className="relative inline-block">
                <span className="bg-gradient-to-r from-amber-400 via-orange-400 to-rose-400 bg-clip-text text-transparent">
                  AI Best Friend
                </span>
                <span
                  aria-hidden="true"
                  className="absolute -bottom-2 left-0 right-0 h-1 rounded-full bg-gradient-to-r from-amber-400 via-orange-400 to-rose-400 opacity-60"
                />
              </span>
            </h1>

            <p className="max-w-2xl text-lg sm:text-xl text-zinc-400 leading-relaxed">
              SuperPilot combines cutting-edge AI with deep canine science to help you train smarter,
              monitor health proactively, track every adventure, and truly understand your dog&apos;s world.
            </p>

            <div className="flex flex-col sm:flex-row items-center gap-4">
              <a
                href="#signup"
                className="inline-flex items-center gap-2 bg-amber-400 text-zinc-900 font-bold px-8 py-3.5 rounded-full text-base hover:bg-amber-300 transition-colors shadow-lg shadow-amber-500/20"
              >
                Start Free Trial
                <ArrowRightIcon />
              </a>
              <button
                type="button"
                className="inline-flex items-center gap-2.5 border border-white/20 text-white font-semibold px-8 py-3.5 rounded-full text-base hover:bg-white/5 hover:border-white/40 transition-colors"
              >
                <span className="w-7 h-7 rounded-full bg-white/10 flex items-center justify-center">
                  <PlayIcon />
                </span>
                Watch Demo
              </button>
            </div>

            <p className="text-zinc-500 text-sm">
              Trusted by{" "}
              <span className="text-white font-semibold">50,000+</span> dog owners worldwide
            </p>
          </div>

          <PawPrint className="absolute bottom-10 left-10 w-16 h-16 text-indigo-500/10 rotate-12" />
          <PawPrint className="absolute top-20 right-16 w-10 h-10 text-violet-500/10 -rotate-6" />
          <PawPrint className="absolute bottom-20 right-32 w-8 h-8 text-amber-500/10 rotate-45" />
        </section>

        {/* Features */}
        <section
          id="features"
          className="py-24 px-6 bg-zinc-900/50"
          aria-labelledby="features-heading"
        >
          <div className="max-w-7xl mx-auto">
            <div className="text-center mb-16">
              <p className="text-sm font-semibold uppercase tracking-widest text-indigo-400 mb-3">
                What SuperPilot Does
              </p>
              <h2
                id="features-heading"
                className="text-4xl sm:text-5xl font-extrabold tracking-tight text-white"
              >
                Everything your dog needs,{" "}
                <br className="hidden sm:block" />
                powered by AI
              </h2>
              <p className="mt-4 text-zinc-400 max-w-xl mx-auto">
                Four intelligent systems working together, so you can focus on the joy of having a dog.
              </p>
            </div>

            <ul className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
              {features.map((feature) => (
                <li
                  key={feature.title}
                  className={`relative rounded-2xl border ${feature.border} bg-zinc-900 p-7 flex flex-col gap-4 transition-all group`}
                >
                  <div
                    aria-hidden="true"
                    className={`absolute inset-0 rounded-2xl bg-gradient-to-br ${feature.accent} opacity-0 group-hover:opacity-[0.05] transition-opacity`}
                  />
                  <div className={`w-12 h-12 rounded-xl ${feature.bg} ${feature.text} flex items-center justify-center flex-shrink-0`}>
                    {feature.icon}
                  </div>
                  <h3 className="text-lg font-bold text-white">{feature.title}</h3>
                  <p className="text-sm text-zinc-400 leading-relaxed">{feature.description}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* Social Proof */}
        <section
          id="testimonials"
          className="py-24 px-6"
          aria-labelledby="testimonials-heading"
        >
          <div className="max-w-7xl mx-auto">
            <div className="text-center mb-16">
              <p className="text-sm font-semibold uppercase tracking-widest text-indigo-400 mb-3">
                Real Stories
              </p>
              <h2
                id="testimonials-heading"
                className="text-4xl sm:text-5xl font-extrabold tracking-tight text-white"
              >
                Trusted by{" "}
                <span className="bg-gradient-to-r from-amber-400 to-orange-400 bg-clip-text text-transparent">
                  50,000+
                </span>{" "}
                dog owners
              </h2>
              <p className="mt-4 text-zinc-400 max-w-lg mx-auto">
                From first-time dog parents to seasoned breeders, SuperPilot makes a difference every day.
              </p>
            </div>

            <ul className="grid grid-cols-1 md:grid-cols-3 gap-6">
              {testimonials.map((t) => (
                <li
                  key={t.name}
                  className="rounded-2xl border border-zinc-800 bg-zinc-900 p-7 flex flex-col gap-5"
                >
                  <StarRating />
                  <blockquote>
                    <p className="text-zinc-300 text-base leading-relaxed">
                      &ldquo;{t.quote}&rdquo;
                    </p>
                  </blockquote>
                  <div className="flex items-center gap-3 mt-auto pt-4 border-t border-zinc-800">
                    <div
                      className={`w-10 h-10 rounded-full ${t.avatarBg} flex items-center justify-center text-white font-bold text-sm flex-shrink-0`}
                      aria-hidden="true"
                    >
                      {t.initials}
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-white">{t.name}</p>
                      <p className="text-xs text-zinc-500">{t.dog}</p>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* Partners */}
        <section
          className="py-20 px-6 bg-zinc-900/50"
          aria-labelledby="partners-heading"
        >
          <div className="max-w-7xl mx-auto flex flex-col items-center gap-10">
            <div className="text-center">
              <p className="text-sm font-semibold uppercase tracking-widest text-indigo-400 mb-3">
                Ecosystem
              </p>
              <h2
                id="partners-heading"
                className="text-3xl sm:text-4xl font-extrabold tracking-tight text-white"
              >
                Our Trusted Partners
              </h2>
              <p className="mt-3 text-zinc-400 max-w-md mx-auto">
                We collaborate with the best in pet technology and veterinary science.
              </p>
            </div>

            <ul className="grid grid-cols-2 lg:grid-cols-4 gap-4 w-full max-w-4xl">
              {partners.map((partner) => (
                <li
                  key={partner.name}
                  className="rounded-2xl border border-zinc-800 bg-zinc-900 px-6 py-5 flex flex-col gap-1 items-center text-center hover:border-indigo-500/40 hover:bg-zinc-800/60 transition-all"
                >
                  <span className="text-lg font-bold text-white">{partner.name}</span>
                  <span className="text-xs text-zinc-500">{partner.tagline}</span>
                </li>
              ))}
            </ul>

            <Link
              href="/partners"
              className="inline-flex items-center gap-2 text-sm font-semibold text-indigo-400 hover:text-indigo-300 transition-colors group"
            >
              View all partners
              <span className="transition-transform group-hover:translate-x-1">
                <ArrowRightIcon />
              </span>
            </Link>
          </div>
        </section>

        {/* CTA */}
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

      </main>

      {/* Footer */}
      <footer className="border-t border-zinc-800 py-10 px-6">
        <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4 text-sm text-zinc-500">
          <div className="flex items-center gap-2">
            <PawPrint className="w-5 h-5 text-amber-400" />
            <span className="font-semibold text-white">
              Super<span className="text-amber-400">Pilot</span>
            </span>
          </div>
          <p>&copy; {new Date().getFullYear()} SuperPilot. All rights reserved.</p>
          <nav className="flex gap-6" aria-label="Footer navigation">
            <a href="#" className="hover:text-zinc-300 transition-colors">Privacy</a>
            <a href="#" className="hover:text-zinc-300 transition-colors">Terms</a>
            <Link href="/partners" className="hover:text-zinc-300 transition-colors">Partners</Link>
          </nav>
        </div>
      </footer>

    </div>
  );
}
