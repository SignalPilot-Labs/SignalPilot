import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "SuperPilot — Your Dog Deserves AI",
  description:
    "SuperPilot uses cutting-edge artificial intelligence to understand, train, and care for your furry companion like never before.",
};

// ─── SVG Icons ────────────────────────────────────────────────────────────────

function HeartPulseIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="w-8 h-8"
    >
      <path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z" />
      <path d="M3.22 12H9.5l1.5-3 2 4.5 1.5-3 1 1.5h3.78" />
    </svg>
  );
}

function BrainIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="w-8 h-8"
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

function MicIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="w-8 h-8"
    >
      <rect x="9" y="2" width="6" height="11" rx="3" />
      <path d="M5 10a7 7 0 0 0 14 0" />
      <line x1="12" y1="19" x2="12" y2="22" />
      <line x1="8" y1="22" x2="16" y2="22" />
      <path d="M9 9h1M14 9h1M9 6h1M14 6h1" />
    </svg>
  );
}

function CollarIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="w-7 h-7"
    >
      <circle cx="12" cy="8" r="6" />
      <path d="M6.2 10.8 5 22h14l-1.2-11.2" />
      <path d="M10 22v-2a2 2 0 0 1 4 0v2" />
    </svg>
  );
}

function BluetoothIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="w-7 h-7"
    >
      <polyline points="6.5 6.5 17.5 17.5 12 23 12 1 17.5 6.5 6.5 17.5" />
    </svg>
  );
}

function SparkleIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="w-7 h-7"
    >
      <path d="M12 3c-1 3-2.5 4.5-5.5 5.5C9.5 9.5 11 11 12 14c1-3 2.5-4.5 5.5-5.5C14.5 7.5 13 6 12 3Z" />
      <path d="M5 14c-.5 1.5-1.5 2.5-3 3 1.5.5 2.5 1.5 3 3 .5-1.5 1.5-2.5 3-3-1.5-.5-2.5-1.5-3-3Z" />
      <path d="M19 3c-.5 1.5-1.5 2.5-3 3 1.5.5 2.5 1.5 3 3 .5-1.5 1.5-2.5 3-3-1.5-.5-2.5-1.5-3-3Z" />
    </svg>
  );
}

function StarIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
      className="w-4 h-4"
    >
      <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
    </svg>
  );
}

function PawPrintIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
      className="w-5 h-5"
    >
      <ellipse cx="6" cy="7" rx="1.5" ry="2" />
      <ellipse cx="10.5" cy="5" rx="1.5" ry="2" />
      <ellipse cx="13.5" cy="5" rx="1.5" ry="2" />
      <ellipse cx="18" cy="7" rx="1.5" ry="2" />
      <path d="M12 22c-4 0-7-3-7-6 0-2 1.5-3.5 3.5-3.5.7 0 1.3.2 1.8.5.3.2.6.3.7.3s.4-.1.7-.3c.5-.3 1.1-.5 1.8-.5 2 0 3.5 1.5 3.5 3.5 0 3-3 6-7 6z" />
    </svg>
  );
}

// ─── Data ─────────────────────────────────────────────────────────────────────

const features = [
  {
    icon: <HeartPulseIcon />,
    title: "AI Health Monitor",
    description:
      "Real-time health tracking powered by computer vision. Detects changes in gait, energy, and mood before you even notice something's off.",
    color: "text-brand-pink",
    bg: "bg-brand-pink/10",
    border: "border-brand-pink/20",
  },
  {
    icon: <BrainIcon />,
    title: "Smart Training",
    description:
      "Personalized training programs that adapt to your dog's unique learning style, attention span, and treat preferences. Yes, treat preferences.",
    color: "text-brand-purple",
    bg: "bg-brand-purple/10",
    border: "border-brand-purple/20",
  },
  {
    icon: <MicIcon />,
    title: "Bark Translator",
    description:
      "Yes, we actually translate barks. Patent pending. Our model was trained on 12 million bark samples across 150+ breeds. The results are… illuminating.",
    color: "text-brand-teal",
    bg: "bg-brand-teal/10",
    border: "border-brand-teal/20",
  },
];

const stats = [
  { value: "50,000+", label: "Happy Dogs" },
  { value: "99.7%", label: "Bark Accuracy" },
  { value: "150+", label: "Breeds Supported" },
  { value: "24/7", label: "AI Monitoring" },
];

const steps = [
  {
    number: "01",
    icon: <CollarIcon />,
    title: "Collar Up",
    description:
      "Attach the SuperPilot smart collar. It's lightweight, waterproof, and frankly better looking than most human wearables.",
  },
  {
    number: "02",
    icon: <BluetoothIcon />,
    title: "Connect",
    description:
      "Pair with our app via Bluetooth in under 30 seconds. No PhD required. If your dog can sit on command, you can handle this.",
  },
  {
    number: "03",
    icon: <SparkleIcon />,
    title: "Relax",
    description:
      "Our AI takes care of the rest — monitoring, training nudges, health alerts, and daily bark summaries delivered straight to your phone.",
  },
];

const testimonials = [
  {
    quote:
      "I used to wonder what Biscuit was thinking when he stared at me at 3 AM. Now SuperPilot tells me it's 'mild existential dread and a strong desire for cheese.' Finally, closure.",
    name: "Margaret T.",
    dog: "Biscuit, 4-yr-old Golden Retriever",
    rating: 5,
  },
  {
    quote:
      "My vet said Duke's anxiety was improving. I said I know, the AI told me last Tuesday. The look on her face was worth every penny of the subscription.",
    name: "Carlos R.",
    dog: "Duke, 7-yr-old French Bulldog",
    rating: 5,
  },
  {
    quote:
      "Turns out 80% of Pretzel's barks translate to 'squirrel.' The other 20% is 'bigger squirrel.' I don't know what I expected but this feels right.",
    name: "Yuki N.",
    dog: "Pretzel, 2-yr-old Shiba Inu",
    rating: 5,
  },
];

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function Home() {
  return (
    <div className="min-h-screen font-sans overflow-x-hidden">
      {/* ── Hero ────────────────────────────────────────────────────────────── */}
      <section
        className="relative min-h-screen flex items-center justify-center pt-20 pb-32 overflow-hidden"
        style={{
          background:
            "linear-gradient(135deg, #1a1a2e 0%, #16213e 40%, #2d1b69 80%, #6c5ce7 100%)",
        }}
        aria-label="Hero"
      >
        {/* Decorative blobs */}
        <div
          className="absolute top-1/4 left-1/4 w-96 h-96 rounded-full opacity-20 blur-3xl pointer-events-none"
          style={{ background: "#6c5ce7" }}
          aria-hidden="true"
        />
        <div
          className="absolute bottom-1/4 right-1/4 w-80 h-80 rounded-full opacity-15 blur-3xl pointer-events-none"
          style={{ background: "#00cec9" }}
          aria-hidden="true"
        />
        <div
          className="absolute top-1/2 right-1/3 w-64 h-64 rounded-full opacity-10 blur-3xl pointer-events-none"
          style={{ background: "#fd79a8" }}
          aria-hidden="true"
        />

        {/* Grid texture */}
        <div
          className="absolute inset-0 opacity-5 pointer-events-none"
          style={{
            backgroundImage:
              "linear-gradient(rgba(255,255,255,0.1) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.1) 1px, transparent 1px)",
            backgroundSize: "60px 60px",
          }}
          aria-hidden="true"
        />

        <div className="relative max-w-5xl mx-auto px-6 text-center">
          <div className="inline-flex items-center gap-2 bg-white/10 border border-white/15 rounded-full px-4 py-1.5 mb-8">
            <span className="text-brand-teal text-xs font-bold uppercase tracking-widest">
              Now in Public Beta
            </span>
            <span className="text-brand-pink" aria-hidden="true">
              <PawPrintIcon />
            </span>
          </div>

          <h1 className="text-5xl sm:text-6xl lg:text-8xl font-black text-white leading-[1.05] tracking-tight mb-8">
            Your Dog{" "}
            <span
              style={{
                backgroundImage: "linear-gradient(90deg, #a29bfe, #fd79a8)",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                backgroundClip: "text",
              }}
            >
              Deserves
            </span>{" "}
            AI
          </h1>

          <p className="text-lg sm:text-xl text-white/65 max-w-2xl mx-auto leading-relaxed mb-12">
            SuperPilot uses cutting-edge artificial intelligence to understand,
            train, and care for your furry companion like never before.
          </p>

          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <a
              href="#signup"
              className="w-full sm:w-auto inline-flex items-center justify-center gap-2 bg-brand-purple hover:bg-brand-purple-dark text-white font-bold px-8 py-4 rounded-full text-base transition-colors duration-200 shadow-lg"
              style={{ boxShadow: "0 0 40px rgba(108, 92, 231, 0.5)" }}
            >
              Get Started
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 20 20"
                fill="currentColor"
                className="w-4 h-4"
                aria-hidden="true"
              >
                <path
                  fillRule="evenodd"
                  d="M3 10a.75.75 0 0 1 .75-.75h10.638L10.23 5.29a.75.75 0 1 1 1.04-1.08l5.5 5.25a.75.75 0 0 1 0 1.08l-5.5 5.25a.75.75 0 1 1-1.04-1.08l4.158-3.96H3.75A.75.75 0 0 1 3 10Z"
                  clipRule="evenodd"
                />
              </svg>
            </a>
            <a
              href="#how-it-works"
              className="w-full sm:w-auto inline-flex items-center justify-center gap-2 border border-white/25 hover:border-white/50 text-white font-bold px-8 py-4 rounded-full text-base transition-colors duration-200"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 20 20"
                fill="currentColor"
                className="w-4 h-4"
                aria-hidden="true"
              >
                <path d="M6.3 2.841A1.5 1.5 0 0 0 4 4.11V15.89a1.5 1.5 0 0 0 2.3 1.269l9.344-5.89a1.5 1.5 0 0 0 0-2.538L6.3 2.84Z" />
              </svg>
              Watch Demo
            </a>
          </div>

          {/* Social proof micro-strip */}
          <div className="mt-16 flex flex-col sm:flex-row items-center justify-center gap-6 text-white/50 text-sm">
            <div className="flex items-center gap-1.5">
              <span className="flex text-yellow-400">
                {Array.from({ length: 5 }).map((_, i) => (
                  <StarIcon key={i} />
                ))}
              </span>
              <span>4.9 from 2,400+ reviews</span>
            </div>
            <span className="hidden sm:block text-white/20" aria-hidden="true">
              |
            </span>
            <span>No credit card required</span>
            <span className="hidden sm:block text-white/20" aria-hidden="true">
              |
            </span>
            <span>Cancel anytime</span>
          </div>
        </div>

        {/* Bottom fade */}
        <div
          className="absolute bottom-0 left-0 right-0 h-32 pointer-events-none"
          style={{
            background:
              "linear-gradient(to bottom, transparent, rgb(15 15 26))",
          }}
          aria-hidden="true"
        />
      </section>

      {/* ── Features ────────────────────────────────────────────────────────── */}
      <section
        id="features"
        className="py-28 px-6"
        style={{ background: "#0f0f1a" }}
        aria-labelledby="features-heading"
      >
        <div className="max-w-7xl mx-auto">
          <div className="text-center mb-20">
            <p className="text-brand-teal text-xs font-bold uppercase tracking-widest mb-4">
              What We Do
            </p>
            <h2
              id="features-heading"
              className="text-4xl sm:text-5xl font-black text-white leading-tight mb-6"
            >
              Built for dogs.
              <br />
              <span className="text-white/40">Engineered for peace of mind.</span>
            </h2>
            <p className="text-white/50 max-w-xl mx-auto text-lg leading-relaxed">
              Three core pillars of the SuperPilot platform, each powered by our
              proprietary canine AI model — PupGPT-7.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {features.map((f) => (
              <article
                key={f.title}
                className={`relative rounded-2xl border p-8 flex flex-col gap-5 transition-transform duration-300 hover:-translate-y-1 ${f.border}`}
                style={{ background: "rgba(255,255,255,0.03)" }}
              >
                <div
                  className={`w-14 h-14 rounded-xl flex items-center justify-center ${f.bg} ${f.color}`}
                >
                  {f.icon}
                </div>
                <div>
                  <h3 className="text-white font-bold text-xl mb-2">
                    {f.title}
                  </h3>
                  <p className="text-white/55 leading-relaxed text-sm">
                    {f.description}
                  </p>
                </div>
                <div
                  className={`absolute top-0 right-0 w-24 h-24 rounded-full opacity-10 blur-2xl pointer-events-none ${f.bg}`}
                  aria-hidden="true"
                />
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* ── Stats ───────────────────────────────────────────────────────────── */}
      <section
        className="py-24 px-6"
        style={{ background: "#1a1a2e" }}
        aria-label="Stats"
      >
        <div className="max-w-7xl mx-auto">
          <dl className="grid grid-cols-2 lg:grid-cols-4 gap-px rounded-2xl overflow-hidden border border-white/10">
            {stats.map((stat, i) => (
              <div
                key={stat.label}
                className={`flex flex-col items-center justify-center py-12 px-6 text-center ${
                  i % 2 === 0 ? "bg-white/[0.04]" : "bg-white/[0.02]"
                }`}
              >
                <dt className="order-2 text-white/50 text-sm font-medium mt-2">
                  {stat.label}
                </dt>
                <dd
                  className="order-1 text-4xl sm:text-5xl font-black"
                  style={{
                    backgroundImage:
                      "linear-gradient(135deg, #a29bfe, #00cec9)",
                    WebkitBackgroundClip: "text",
                    WebkitTextFillColor: "transparent",
                    backgroundClip: "text",
                  }}
                >
                  {stat.value}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      {/* ── How It Works ────────────────────────────────────────────────────── */}
      <section
        id="how-it-works"
        className="py-28 px-6"
        style={{ background: "#0f0f1a" }}
        aria-labelledby="how-heading"
      >
        <div className="max-w-7xl mx-auto">
          <div className="text-center mb-20">
            <p className="text-brand-pink text-xs font-bold uppercase tracking-widest mb-4">
              Get Started
            </p>
            <h2
              id="how-heading"
              className="text-4xl sm:text-5xl font-black text-white leading-tight mb-6"
            >
              Up and running in{" "}
              <span
                style={{
                  backgroundImage: "linear-gradient(90deg, #fd79a8, #a29bfe)",
                  WebkitBackgroundClip: "text",
                  WebkitTextFillColor: "transparent",
                  backgroundClip: "text",
                }}
              >
                three steps.
              </span>
            </h2>
            <p className="text-white/50 max-w-xl mx-auto text-lg leading-relaxed">
              We promise it takes less time than getting your dog to sit on
              command. Well, most dogs.
            </p>
          </div>

          <div className="relative grid grid-cols-1 md:grid-cols-3 gap-8">
            {/* Connecting line */}
            <div
              className="hidden md:block absolute top-10 left-[16.666%] right-[16.666%] h-px"
              style={{
                background:
                  "linear-gradient(to right, #6c5ce7, #00cec9, #fd79a8)",
              }}
              aria-hidden="true"
            />

            {steps.map((step, i) => {
              const colors = [
                { number: "text-brand-purple", ring: "border-brand-purple/40", glow: "#6c5ce7" },
                { number: "text-brand-teal", ring: "border-brand-teal/40", glow: "#00cec9" },
                { number: "text-brand-pink", ring: "border-brand-pink/40", glow: "#fd79a8" },
              ];
              const c = colors[i];
              return (
                <div key={step.number} className="flex flex-col items-center text-center gap-5">
                  <div className="relative">
                    <div
                      className={`w-20 h-20 rounded-full border-2 ${c.ring} flex items-center justify-center`}
                      style={{
                        background: "rgba(255,255,255,0.04)",
                        boxShadow: `0 0 30px ${c.glow}33`,
                      }}
                    >
                      <span className={`${c.number} font-black text-2xl`}>
                        {step.number}
                      </span>
                    </div>
                  </div>
                  <div
                    className={`w-12 h-12 rounded-xl flex items-center justify-center text-white/60`}
                    style={{ background: "rgba(255,255,255,0.06)" }}
                  >
                    {step.icon}
                  </div>
                  <div>
                    <h3 className="text-white font-bold text-xl mb-3">
                      {step.title}
                    </h3>
                    <p className="text-white/50 text-sm leading-relaxed max-w-xs mx-auto">
                      {step.description}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* ── Testimonials ────────────────────────────────────────────────────── */}
      <section
        id="testimonials"
        className="py-28 px-6"
        style={{ background: "#1a1a2e" }}
        aria-labelledby="testimonials-heading"
      >
        <div className="max-w-7xl mx-auto">
          <div className="text-center mb-20">
            <p className="text-brand-purple-light text-xs font-bold uppercase tracking-widest mb-4">
              Testimonials
            </p>
            <h2
              id="testimonials-heading"
              className="text-4xl sm:text-5xl font-black text-white leading-tight"
            >
              Real dogs. Real owners.
              <br />
              <span className="text-white/40">Real bewilderment.</span>
            </h2>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {testimonials.map((t, i) => {
              const accents = [
                "border-brand-purple/30",
                "border-brand-teal/30",
                "border-brand-pink/30",
              ];
              const quoteColors = [
                "text-brand-purple-light",
                "text-brand-teal",
                "text-brand-pink",
              ];
              return (
                <figure
                  key={t.name}
                  className={`rounded-2xl border p-8 flex flex-col gap-6 ${accents[i]}`}
                  style={{ background: "rgba(255,255,255,0.03)" }}
                >
                  <div className="flex gap-0.5">
                    {Array.from({ length: t.rating }).map((_, j) => (
                      <span key={j} className="text-yellow-400">
                        <StarIcon />
                      </span>
                    ))}
                  </div>
                  <blockquote>
                    <p className="text-white/75 text-sm leading-relaxed italic">
                      &ldquo;{t.quote}&rdquo;
                    </p>
                  </blockquote>
                  <figcaption className="flex items-center gap-3 mt-auto">
                    <div
                      className={`w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm ${quoteColors[i]}`}
                      style={{ background: "rgba(255,255,255,0.08)" }}
                      aria-hidden="true"
                    >
                      {t.name.charAt(0)}
                    </div>
                    <div>
                      <div className="text-white font-semibold text-sm">
                        {t.name}
                      </div>
                      <div className="text-white/40 text-xs">{t.dog}</div>
                    </div>
                  </figcaption>
                </figure>
              );
            })}
          </div>
        </div>
      </section>

      {/* ── CTA / Signup ────────────────────────────────────────────────────── */}
      <section
        id="signup"
        className="py-28 px-6 relative overflow-hidden"
        style={{
          background:
            "linear-gradient(135deg, #2d1b69 0%, #6c5ce7 50%, #a29bfe 100%)",
        }}
        aria-labelledby="cta-heading"
      >
        {/* Decorative blobs */}
        <div
          className="absolute top-0 left-0 w-96 h-96 rounded-full opacity-20 blur-3xl pointer-events-none"
          style={{ background: "#fd79a8", transform: "translate(-50%, -50%)" }}
          aria-hidden="true"
        />
        <div
          className="absolute bottom-0 right-0 w-96 h-96 rounded-full opacity-20 blur-3xl pointer-events-none"
          style={{
            background: "#00cec9",
            transform: "translate(50%, 50%)",
          }}
          aria-hidden="true"
        />

        <div className="relative max-w-2xl mx-auto text-center">
          <span className="text-white/80 text-4xl mb-6 block" aria-hidden="true">
            🐾
          </span>
          <h2
            id="cta-heading"
            className="text-4xl sm:text-5xl font-black text-white leading-tight mb-6"
          >
            Ready to SuperPilot
            <br />
            Your Pup?
          </h2>
          <p className="text-white/70 text-lg mb-10 leading-relaxed">
            Join 50,000+ dog owners who finally know what their dog is thinking.
            (Spoiler: it&apos;s mostly food.)
          </p>

          <form
            className="flex flex-col sm:flex-row gap-3 max-w-md mx-auto"
            aria-label="Email signup form"
          >
            <label htmlFor="email-signup" className="sr-only">
              Email address
            </label>
            <input
              id="email-signup"
              type="email"
              placeholder="your@email.com"
              autoComplete="email"
              className="flex-1 bg-white/15 hover:bg-white/20 focus:bg-white/20 border border-white/25 focus:border-white/50 rounded-full px-5 py-3.5 text-white placeholder-white/50 text-sm outline-none transition-colors duration-200"
            />
            <button
              type="submit"
              className="bg-white text-brand-purple hover:bg-white/90 font-bold px-7 py-3.5 rounded-full text-sm whitespace-nowrap transition-colors duration-200"
            >
              Get Early Access
            </button>
          </form>

          <p className="mt-5 text-white/45 text-xs">
            Free 30-day trial. No credit card. No obligations. Just happier
            dogs.
          </p>
        </div>
      </section>

    </div>
  );
}
