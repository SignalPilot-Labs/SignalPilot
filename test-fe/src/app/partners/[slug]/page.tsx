import Link from "next/link";
import { notFound } from "next/navigation";
import { partners, getPartnerBySlug } from "@/data/partners";

export async function generateStaticParams() {
  return partners.map((partner) => ({ slug: partner.slug }));
}

export default async function PartnerDetailPage(
  props: PageProps<"/partners/[slug]">
) {
  const { slug } = await props.params;
  const partner = getPartnerBySlug(slug);

  if (!partner) {
    notFound();
  }

  return (
    <>
      {/* Back link */}
      <div className="max-w-4xl mx-auto px-6 pt-8">
        <Link
          href="/partners"
          className="inline-flex items-center gap-1.5 text-sm transition-colors hover:text-white"
          style={{ color: "#8888aa" }}
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 14 14"
            fill="none"
            aria-hidden="true"
          >
            <path
              d="M11.5 7h-9M6 3.5L2.5 7 6 10.5"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          Back to Partners
        </Link>
      </div>

      {/* Hero */}
      <header className="max-w-4xl mx-auto px-6 pt-10 pb-12">
        <div className="flex flex-col sm:flex-row sm:items-center gap-6">
          <div
            className="w-20 h-20 rounded-2xl flex items-center justify-center text-4xl flex-shrink-0"
            style={{ backgroundColor: "rgba(108,92,231,0.12)" }}
          >
            {partner.emoji}
          </div>
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-3">
              <span
                className="text-xs font-medium px-2.5 py-1 rounded-full"
                style={{
                  backgroundColor: "rgba(0,206,201,0.1)",
                  color: "#00cec9",
                }}
              >
                {partner.category}
              </span>
              <span
                className="text-xs"
                style={{ color: "#55556a" }}
              >
                Est. {partner.founded} &middot; {partner.headquarters}
              </span>
            </div>
            <h1
              className="text-4xl font-bold tracking-tight"
              style={{ color: "#f0f0f8" }}
            >
              {partner.name}
            </h1>
            <p
              className="text-base leading-relaxed"
              style={{ color: "#8888aa" }}
            >
              {partner.tagline}
            </p>
          </div>
        </div>
      </header>

      {/* Divider */}
      <div
        className="max-w-4xl mx-auto px-6"
        style={{ borderTop: "1px solid rgba(108,92,231,0.15)" }}
      />

      {/* Body */}
      <main className="max-w-4xl mx-auto px-6 py-12 flex flex-col gap-12">
        {/* About */}
        <section>
          <h2
            className="text-xl font-semibold mb-4"
            style={{ color: "#f0f0f8" }}
          >
            About {partner.name}
          </h2>
          <p
            className="text-base leading-relaxed"
            style={{ color: "#9999bb" }}
          >
            {partner.description}
          </p>
        </section>

        {/* Key features */}
        <section>
          <h2
            className="text-xl font-semibold mb-5"
            style={{ color: "#f0f0f8" }}
          >
            Key Features
          </h2>
          <ul className="flex flex-col gap-4">
            {partner.keyFeatures.map((feature, i) => (
              <li key={i} className="flex items-start gap-3">
                <span
                  className="mt-0.5 w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0"
                  style={{
                    backgroundColor: "rgba(108,92,231,0.15)",
                    color: "#6c5ce7",
                  }}
                >
                  {i + 1}
                </span>
                <p
                  className="text-base leading-relaxed"
                  style={{ color: "#9999bb" }}
                >
                  {feature}
                </p>
              </li>
            ))}
          </ul>
        </section>

        {/* Integration */}
        <section
          className="rounded-2xl p-6"
          style={{
            backgroundColor: "rgba(108,92,231,0.06)",
            border: "1px solid rgba(108,92,231,0.2)",
          }}
        >
          <div className="flex items-center gap-2 mb-4">
            <svg
              width="18"
              height="18"
              viewBox="0 0 18 18"
              fill="none"
              aria-hidden="true"
            >
              <path
                d="M3 9h12M9 3l6 6-6 6"
                stroke="#6c5ce7"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            <h2
              className="text-xl font-semibold"
              style={{ color: "#f0f0f8" }}
            >
              SuperPilot Integration
            </h2>
          </div>
          <p
            className="text-base leading-relaxed"
            style={{ color: "#9999bb" }}
          >
            {partner.integrationDescription}
          </p>
        </section>

        {/* CTA */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4 pt-2">
          <button
            type="button"
            className="inline-flex items-center gap-2 px-6 py-3 rounded-xl font-semibold text-sm transition-all hover:opacity-90 active:scale-95"
            style={{ backgroundColor: "#6c5ce7", color: "#fff" }}
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 16 16"
              fill="none"
              aria-hidden="true"
            >
              <path
                d="M2 8a6 6 0 1 0 12 0A6 6 0 0 0 2 8Zm6-2v4m0 0 2-2m-2 2L6 10"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            Contact Partner
          </button>
          <Link
            href="/partners"
            className="text-sm transition-colors hover:text-white"
            style={{ color: "#8888aa" }}
          >
            View all partners &rarr;
          </Link>
        </div>
      </main>

    </>
  );
}
