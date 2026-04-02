import Link from "next/link";
import { partners } from "@/data/partners";

export default function PartnersPage() {
  return (
    <>
      {/* Hero */}
      <header className="px-6 py-20 text-center max-w-3xl mx-auto">
        <div
          className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-medium mb-6"
          style={{ backgroundColor: "rgba(108,92,231,0.15)", color: "#6c5ce7" }}
        >
          <span
            className="w-1.5 h-1.5 rounded-full"
            style={{ backgroundColor: "#6c5ce7" }}
          />
          Ecosystem
        </div>
        <h1
          className="text-5xl font-bold tracking-tight mb-4"
          style={{ color: "#f0f0f8" }}
        >
          Our Partners
        </h1>
        <p className="text-lg leading-relaxed" style={{ color: "#8888aa" }}>
          The companies powering the SuperPilot ecosystem — from the collar on
          your dog&rsquo;s neck to the cloud keeping them safe.
        </p>
      </header>

      {/* Grid */}
      <main className="max-w-6xl mx-auto px-6 pb-24">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {partners.map((partner) => (
            <article
              key={partner.slug}
              className="group rounded-2xl p-6 flex flex-col gap-4 transition-all duration-200 hover:-translate-y-0.5"
              style={{
                backgroundColor: "rgba(255,255,255,0.04)",
                border: "1px solid rgba(108,92,231,0.2)",
              }}
            >
              {/* Icon + badge */}
              <div className="flex items-start justify-between">
                <div
                  className="w-12 h-12 rounded-xl flex items-center justify-center text-2xl"
                  style={{ backgroundColor: "rgba(108,92,231,0.12)" }}
                >
                  {partner.emoji}
                </div>
                <span
                  className="text-xs font-medium px-2.5 py-1 rounded-full"
                  style={{
                    backgroundColor: "rgba(0,206,201,0.1)",
                    color: "#00cec9",
                  }}
                >
                  {partner.category}
                </span>
              </div>

              {/* Text */}
              <div className="flex flex-col gap-1 flex-1">
                <h2 className="font-semibold text-lg" style={{ color: "#f0f0f8" }}>
                  {partner.name}
                </h2>
                <p className="text-sm leading-relaxed" style={{ color: "#8888aa" }}>
                  {partner.tagline}
                </p>
              </div>

              {/* Link */}
              <Link
                href={`/partners/${partner.slug}`}
                className="inline-flex items-center gap-1.5 text-sm font-medium transition-colors"
                style={{ color: "#6c5ce7" }}
              >
                Learn More
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 14 14"
                  fill="none"
                  aria-hidden="true"
                  className="transition-transform group-hover:translate-x-0.5"
                >
                  <path
                    d="M2.5 7h9M8 3.5L11.5 7 8 10.5"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </Link>
            </article>
          ))}
        </div>
      </main>

    </>
  );
}
