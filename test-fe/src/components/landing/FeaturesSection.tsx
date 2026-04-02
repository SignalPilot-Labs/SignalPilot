import { BrainIcon, HeartPulseIcon, MapPinIcon, EyeIcon } from "./icons";

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

export default function FeaturesSection() {
  return (
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
  );
}
