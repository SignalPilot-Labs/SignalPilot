import Link from "next/link";
import { ArrowRightIcon } from "./icons";

const partners = [
  { name: "PawTech", tagline: "Smart pet hardware" },
  { name: "VetAI", tagline: "AI veterinary diagnostics" },
  { name: "DoggoHealth", tagline: "Canine wellness data" },
  { name: "BarkSmart", tagline: "Behavioral science" },
];

export default function PartnersPreview() {
  return (
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
  );
}
