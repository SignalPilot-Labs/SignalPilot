import Link from "next/link";
import { notFound } from "next/navigation";

type PartnerData = {
  name: string;
  tagline: string;
  initials: string;
  color: string;
  accentText: string;
  foundingYear: number;
  headquarters: string;
  description: string;
  about: string;
  features: string[];
  integration: string;
};

const partnerData: Record<string, PartnerData> = {
  pawtech: {
    name: "PawTech",
    tagline: "Smart Collars for the Connected Dog",
    initials: "PT",
    color: "bg-indigo-600",
    accentText: "text-indigo-400",
    foundingYear: 2021,
    headquarters: "San Francisco, CA",
    description:
      "PawTech is the leading manufacturer of AI-powered smart collars and wearable devices for dogs. Their hardware combines precision biometric sensors, multi-band GPS, and long-range wireless connectivity to keep pet owners and veterinarians informed at all times.",
    about:
      "Founded in 2021 by a team of hardware engineers and veterinary scientists, PawTech set out to answer a simple question: what if a dog's collar could tell you everything your vet wishes they could measure between visits? Today, more than 200,000 dogs worldwide wear a PawTech collar, generating billions of health data points every month.",
    features: [
      "Continuous heart rate and respiratory rate monitoring with clinical-grade accuracy",
      "Real-time GPS and geofence alerts delivered in under two seconds",
      "Activity and sleep scoring calibrated to breed-specific baselines",
      "Waterproof, chew-resistant housing rated for dogs up to 120 lbs",
    ],
    integration:
      "PawTech collars stream live biometric and location data directly into SuperPilot. The AI engine correlates activity trends, sleep quality, and heart-rate variability to generate daily wellness scores, flag anomalies early, and automatically schedule vet check-ins when thresholds are exceeded — all without the owner lifting a finger.",
  },
  vetai: {
    name: "VetAI",
    tagline: "Clinical Diagnostics, Powered by AI",
    initials: "VA",
    color: "bg-violet-600",
    accentText: "text-violet-400",
    foundingYear: 2020,
    headquarters: "Boston, MA",
    description:
      "VetAI develops machine-learning models trained on tens of millions of veterinary records to assist pet owners and clinicians with early disease detection, lab result interpretation, and treatment pathway recommendations.",
    about:
      "Born out of MIT's Computer Science and Artificial Intelligence Laboratory, VetAI was spun out in 2020 with a mission to democratise access to expert veterinary knowledge. Their diagnostic engine has been validated against board-certified veterinary internists and achieves over 94% accuracy on a panel of 60 common canine conditions.",
    features: [
      "Symptom triage that differentiates urgent from routine concerns in seconds",
      "Lab result parsing with plain-language explanations for owners and flag summaries for vets",
      "Longitudinal health tracking to surface gradual changes invisible in single-snapshot exams",
      "Telehealth scheduling that prioritises appointments based on diagnostic urgency scores",
    ],
    integration:
      "SuperPilot pipes health data from connected devices into VetAI's diagnostic API continuously. When anomalies are detected — whether a spike in resting heart rate or a change in activity patterns — VetAI's models run a differential analysis and surface ranked possibilities inside the SuperPilot dashboard, giving owners clear next steps and giving vets a richer pre-visit picture.",
  },
  doggohealth: {
    name: "DoggoHealth",
    tagline: "Nutrition Science, Tailored to Every Dog",
    initials: "DH",
    color: "bg-amber-500",
    accentText: "text-amber-400",
    foundingYear: 2022,
    headquarters: "Austin, TX",
    description:
      "DoggoHealth combines veterinary nutritionists, food scientists, and machine-learning engineers to create personalised meal plans and supplement protocols for dogs at every life stage.",
    about:
      "DoggoHealth launched in Austin in 2022 after its founders — a pair of veterinary nutritionists frustrated with one-size-fits-all kibble — decided to build the nutrition platform they wished existed. The company now serves over 80,000 dogs with recipes formulated to the gram, accounting for breed, age, weight, activity level, and any known health conditions.",
    features: [
      "Breed- and age-specific macro and micronutrient targets backed by AAFCO and NRC guidelines",
      "Dynamic recipe adjustments when activity data shows significant changes in energy expenditure",
      "Curated supplement add-ons — joint support, coat health, probiotics — with dosage precision",
      "Monthly doorstep delivery of pre-portioned, human-grade ingredients with zero fillers",
    ],
    integration:
      "SuperPilot shares daily caloric expenditure and weight trend data from connected devices with DoggoHealth's nutrition engine. When a dog's activity drops or a growth milestone is reached, DoggoHealth automatically recalculates portion sizes and notifies the owner inside SuperPilot, ensuring every meal matches the dog's real-world energy needs on that day.",
  },
  barksmart: {
    name: "BarkSmart",
    tagline: "Training Devices That Learn With Your Dog",
    initials: "BS",
    color: "bg-fuchsia-600",
    accentText: "text-fuchsia-400",
    foundingYear: 2023,
    headquarters: "Portland, OR",
    description:
      "BarkSmart designs adaptive training hardware and software that uses positive-reinforcement techniques and behavioral AI to help dogs master commands, reduce anxiety, and build confidence — at home, without a professional trainer.",
    about:
      "BarkSmart was founded in Portland in 2023 by animal behaviorists and robotics engineers who believed that great dog training shouldn't require expensive weekly sessions. Their flagship device, the BarkBoard, combines a treat dispenser, microphone array, and camera to run real-time behavioral analysis and deliver precisely timed rewards — the secret to effective conditioning.",
    features: [
      "Computer-vision command recognition that detects sit, stay, heel, and 30+ other behaviors",
      "Adaptive difficulty progression that advances training pace to each dog's learning curve",
      "Anxiety and stress detection using vocalization analysis and body-language cues",
      "Detailed session reports with video highlights and behavioral trend graphs",
    ],
    integration:
      "BarkSmart syncs session outcomes and behavioral scores with SuperPilot after every training session. SuperPilot's AI correlates training progress with sleep quality, activity levels, and health data from other partners to identify whether poor performance on a given day reflects a training plateau or an underlying wellness issue — and recommends the right intervention accordingly.",
  },
};

export function generateStaticParams() {
  return [
    { slug: "pawtech" },
    { slug: "vetai" },
    { slug: "doggohealth" },
    { slug: "barksmart" },
  ];
}

export default async function PartnerPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const partner = partnerData[slug];

  if (!partner) {
    notFound();
  }

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
            <Link href="/partners" className="hover:text-white transition-colors">
              Partners
            </Link>
          </nav>
        </div>
      </header>

      {/* Hero */}
      <section className="mx-auto max-w-6xl px-6 pt-20 pb-14">
        <Link
          href="/partners"
          className="inline-flex items-center gap-1.5 text-sm text-zinc-400 hover:text-zinc-200 transition-colors mb-10"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 16 16"
            fill="currentColor"
            className="h-4 w-4"
            aria-hidden="true"
          >
            <path
              fillRule="evenodd"
              d="M9.78 4.22a.75.75 0 0 1 0 1.06L6.81 8l2.97 2.72a.75.75 0 1 1-1.06 1.06L5.22 8.53a.75.75 0 0 1 0-1.06l3.5-3.25a.75.75 0 0 1 1.06 0Z"
              clipRule="evenodd"
            />
          </svg>
          All Partners
        </Link>

        <div className="flex items-start gap-6">
          <div
            className={`${partner.color} flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl text-white text-xl font-bold shadow-lg`}
          >
            {partner.initials}
          </div>
          <div>
            <p className={`text-sm font-semibold uppercase tracking-widest ${partner.accentText} mb-1`}>
              SuperPilot Partner
            </p>
            <h1 className="text-4xl font-bold tracking-tight text-white mb-2">
              {partner.name}
            </h1>
            <p className="text-lg text-zinc-400">{partner.tagline}</p>
          </div>
        </div>

        {/* Meta pills */}
        <div className="flex flex-wrap gap-3 mt-8">
          <span className="inline-flex items-center gap-2 rounded-full border border-zinc-700 bg-zinc-800/60 px-4 py-1.5 text-xs text-zinc-300">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 16 16"
              fill="currentColor"
              className="h-3.5 w-3.5 text-zinc-500"
              aria-hidden="true"
            >
              <path
                fillRule="evenodd"
                d="M4 1.75a.75.75 0 0 1 1.5 0V3h5V1.75a.75.75 0 0 1 1.5 0V3A2.25 2.25 0 0 1 14 5.25v7.5A2.25 2.25 0 0 1 11.75 15h-7.5A2.25 2.25 0 0 1 2 12.75v-7.5A2.25 2.25 0 0 1 4.25 3V1.75ZM3.5 7.5a.75.75 0 0 1 .75-.75h7.5a.75.75 0 0 1 0 1.5h-7.5A.75.75 0 0 1 3.5 7.5Z"
                clipRule="evenodd"
              />
            </svg>
            Founded {partner.foundingYear}
          </span>
          <span className="inline-flex items-center gap-2 rounded-full border border-zinc-700 bg-zinc-800/60 px-4 py-1.5 text-xs text-zinc-300">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 16 16"
              fill="currentColor"
              className="h-3.5 w-3.5 text-zinc-500"
              aria-hidden="true"
            >
              <path
                fillRule="evenodd"
                d="m7.539 14.841.003.003.002.002a.755.755 0 0 0 .912 0l.002-.002.003-.003.012-.009a5.57 5.57 0 0 0 .19-.153 15.588 15.588 0 0 0 2.046-2.082c1.101-1.399 2.291-3.553 2.291-6.097a5 5 0 0 0-10 0c0 2.544 1.19 4.698 2.291 6.097a15.584 15.584 0 0 0 2.046 2.082 8.916 8.916 0 0 0 .19.153l.012.01ZM8 8.5a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z"
                clipRule="evenodd"
              />
            </svg>
            {partner.headquarters}
          </span>
        </div>
      </section>

      {/* Divider */}
      <div className="mx-auto max-w-6xl px-6">
        <div className="h-px bg-gradient-to-r from-transparent via-zinc-700 to-transparent" />
      </div>

      {/* Body */}
      <div className="mx-auto max-w-6xl px-6 py-16 grid gap-12 lg:grid-cols-3">
        {/* Main content */}
        <div className="lg:col-span-2 flex flex-col gap-12">
          {/* About */}
          <section>
            <h2 className="text-xs font-semibold uppercase tracking-widest text-zinc-500 mb-4">
              About
            </h2>
            <p className="text-zinc-300 leading-relaxed mb-4">
              {partner.description}
            </p>
            <p className="text-zinc-400 leading-relaxed">{partner.about}</p>
          </section>

          {/* Key features */}
          <section>
            <h2 className="text-xs font-semibold uppercase tracking-widest text-zinc-500 mb-4">
              Key Features
            </h2>
            <ul className="flex flex-col gap-3">
              {partner.features.map((feature, i) => (
                <li key={i} className="flex items-start gap-3">
                  <span
                    className={`mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-full ${partner.color} text-white`}
                    aria-hidden="true"
                  >
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      viewBox="0 0 16 16"
                      fill="currentColor"
                      className="h-3 w-3"
                    >
                      <path
                        fillRule="evenodd"
                        d="M12.416 3.376a.75.75 0 0 1 .208 1.04l-5 7.5a.75.75 0 0 1-1.154.114l-3-3a.75.75 0 0 1 1.06-1.06l2.353 2.353 4.493-6.74a.75.75 0 0 1 1.04-.207Z"
                        clipRule="evenodd"
                      />
                    </svg>
                  </span>
                  <span className="text-zinc-300 leading-relaxed text-sm">
                    {feature}
                  </span>
                </li>
              ))}
            </ul>
          </section>

          {/* Integration */}
          <section className="rounded-2xl border border-indigo-500/20 bg-indigo-950/30 p-8">
            <h2 className="text-xs font-semibold uppercase tracking-widest text-indigo-400 mb-4">
              Integration with SuperPilot
            </h2>
            <p className="text-zinc-300 leading-relaxed text-sm">
              {partner.integration}
            </p>
          </section>
        </div>

        {/* Sidebar */}
        <aside className="flex flex-col gap-6">
          <div className="rounded-2xl border border-zinc-800 bg-zinc-900 p-6">
            <h3 className="text-xs font-semibold uppercase tracking-widest text-zinc-500 mb-5">
              Quick Facts
            </h3>
            <dl className="flex flex-col gap-4">
              <div>
                <dt className="text-xs text-zinc-500 mb-0.5">Partner since</dt>
                <dd className="text-sm font-medium text-zinc-200">2024</dd>
              </div>
              <div>
                <dt className="text-xs text-zinc-500 mb-0.5">Founded</dt>
                <dd className="text-sm font-medium text-zinc-200">{partner.foundingYear}</dd>
              </div>
              <div>
                <dt className="text-xs text-zinc-500 mb-0.5">Headquarters</dt>
                <dd className="text-sm font-medium text-zinc-200">{partner.headquarters}</dd>
              </div>
              <div>
                <dt className="text-xs text-zinc-500 mb-0.5">Integration status</dt>
                <dd className="inline-flex items-center gap-1.5 text-sm font-medium text-emerald-400">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" aria-hidden="true" />
                  Active
                </dd>
              </div>
            </dl>
          </div>

          <div className="rounded-2xl border border-amber-500/20 bg-amber-950/20 p-6">
            <p className="text-xs font-semibold uppercase tracking-widest text-amber-400 mb-2">
              Ecosystem Partner
            </p>
            <p className="text-sm text-zinc-400 leading-relaxed mb-4">
              {partner.name} is a verified member of the SuperPilot partner ecosystem. Data sharing is encrypted end-to-end.
            </p>
            <Link
              href="/partners"
              className="inline-flex items-center gap-1.5 text-sm font-medium text-amber-400 hover:text-amber-300 transition-colors"
            >
              View all partners
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
        </aside>
      </div>

      {/* CTA */}
      <section className="border-t border-zinc-800">
        <div className="mx-auto max-w-6xl px-6 py-14 flex flex-col sm:flex-row items-center justify-between gap-6">
          <div>
            <h2 className="text-xl font-semibold text-white mb-1">
              Explore the full ecosystem
            </h2>
            <p className="text-sm text-zinc-400">
              Discover how every SuperPilot partner works together.
            </p>
          </div>
          <Link
            href="/partners"
            className="inline-flex items-center gap-2 rounded-full bg-indigo-600 px-6 py-3 text-sm font-semibold text-white hover:bg-indigo-500 transition-colors"
          >
            Back to Partners
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
          <Link href="/about" className="hover:text-zinc-300 transition-colors">
            About SuperPilot
          </Link>
        </div>
      </footer>
    </div>
  );
}
