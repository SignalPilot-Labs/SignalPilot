const teamMembers = [
  {
    name: "Dr. Maya Chen",
    title: "Co-founder & CEO",
    dogFact:
      "Her golden retriever Biscuit was the first dog to wear a SuperPilot prototype. He's been getting treats on demand ever since.",
    initials: "MC",
    accent: "#6c5ce7",
  },
  {
    name: "Jordan Okafor",
    title: "Co-founder & CTO",
    dogFact:
      "Adopted a border collie named Tensor during a hackathon weekend. Tensor learned 'sit' in six minutes; Jordan uses that metric in every investor deck.",
    initials: "JO",
    accent: "#00cec9",
  },
  {
    name: "Priya Nambiar",
    title: "Head of AI Research",
    dogFact:
      "Her rescue dachshund Pretzel has generated more labeled training data than any other dog in the dataset — 14 months of continuous tracking.",
    initials: "PN",
    accent: "#fd79a8",
  },
  {
    name: "Luca Ferretti",
    title: "VP of Design",
    dogFact:
      "Owns three pugs named Serif, Sans, and Mono. The SuperPilot logo is secretly modeled on Serif's silhouette from above.",
    initials: "LF",
    accent: "#6c5ce7",
  },
];

const values = [
  {
    icon: (
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path
          d="M12 2a1 1 0 0 1 .894.553l2.184 4.426 4.886.71a1 1 0 0 1 .555 1.705l-3.535 3.446.835 4.866a1 1 0 0 1-1.451 1.054L12 16.347l-4.368 2.297a1 1 0 0 1-1.45-1.054l.834-4.866L3.48 9.394a1 1 0 0 1 .555-1.705l4.887-.71L11.106 2.553A1 1 0 0 1 12 2Z"
          fill="#6c5ce7"
          opacity="0.2"
        />
        <path
          d="M12 2a1 1 0 0 1 .894.553l2.184 4.426 4.886.71a1 1 0 0 1 .555 1.705l-3.535 3.446.835 4.866a1 1 0 0 1-1.451 1.054L12 16.347l-4.368 2.297a1 1 0 0 1-1.45-1.054l.834-4.866L3.48 9.394a1 1 0 0 1 .555-1.705l4.887-.71L11.106 2.553A1 1 0 0 1 12 2Z"
          stroke="#6c5ce7"
          strokeWidth="1.5"
        />
      </svg>
    ),
    title: "Innovation",
    description:
      "We build things that didn't exist before. If a dog can benefit from it and the physics checks out, we'll try it.",
  },
  {
    icon: (
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path
          d="M12 21c-4.97-3.5-8-6.685-8-9.5A5 5 0 0 1 12 7a5 5 0 0 1 8 4.5c0 2.815-3.03 6-8 9.5Z"
          fill="#fd79a8"
          opacity="0.2"
          stroke="#fd79a8"
          strokeWidth="1.5"
          strokeLinejoin="round"
        />
      </svg>
    ),
    title: "Compassion",
    description:
      "Every decision runs through a simple filter: is this better for dogs? Then: is this better for the humans who love them?",
  },
  {
    icon: (
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <circle cx="12" cy="12" r="9" fill="#00cec9" opacity="0.15" stroke="#00cec9" strokeWidth="1.5" />
        <path d="M12 8v4l2.5 2.5" stroke="#00cec9" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
    title: "Transparency",
    description:
      "Your dog's data is yours. We publish our model cards, our training data policies, and our error rates — even the embarrassing ones.",
  },
  {
    icon: (
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path
          d="M5 15c-1 2 0 4 2 4s3-1 3-3-1-3-3-3c-1 0-2 1-2 2Zm14 0c1 2 0 4-2 4s-3-1-3-3 1-3 3-3c1 0 2 1 2 2Z"
          fill="#6c5ce7"
          opacity="0.2"
          stroke="#6c5ce7"
          strokeWidth="1.5"
        />
        <path d="M7 15c0-5 10-5 10 0" stroke="#6c5ce7" strokeWidth="1.5" strokeLinecap="round" />
        <path d="M10 19c0 1 .5 2 2 2s2-1 2-2" stroke="#fd79a8" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
    title: "Tail Wags",
    description:
      "The ultimate metric. If the dogs aren't happier, healthier, and more connected to their humans, we haven't succeeded.",
  },
];

export default function AboutPage() {
  return (
    <>
      {/* Hero */}
      <header className="max-w-4xl mx-auto px-6 py-20 text-center">
        <div
          className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-medium mb-6"
          style={{ backgroundColor: "rgba(253,121,168,0.12)", color: "#fd79a8" }}
        >
          <span
            className="w-1.5 h-1.5 rounded-full"
            style={{ backgroundColor: "#fd79a8" }}
          />
          Our Story
        </div>
        <h1
          className="text-5xl font-bold tracking-tight mb-5"
          style={{ color: "#f0f0f8" }}
        >
          Built by dog lovers.{" "}
          <span style={{ color: "#6c5ce7" }}>Powered by AI.</span>
        </h1>
        <p
          className="text-lg leading-relaxed max-w-2xl mx-auto"
          style={{ color: "#8888aa" }}
        >
          We started SuperPilot because our dogs deserved better than a squeaky toy and a YouTube tutorial.
        </p>
      </header>

      <main className="max-w-4xl mx-auto px-6 pb-24 flex flex-col gap-20">
        {/* Company story */}
        <section
          className="rounded-2xl p-8 sm:p-10"
          style={{
            backgroundColor: "rgba(255,255,255,0.03)",
            border: "1px solid rgba(108,92,231,0.15)",
          }}
        >
          <h2 className="text-2xl font-bold mb-6" style={{ color: "#f0f0f8" }}>
            How We Got Here
          </h2>
          <div className="flex flex-col gap-4 text-base leading-relaxed" style={{ color: "#9999bb" }}>
            <p>
              Founded in 2024 by a team of dog lovers and AI researchers who met at a
              machine learning conference — and discovered they&rsquo;d all spent the previous
              week watching helplessly as their dogs ignored perfectly reasonable commands.
              The problem wasn&rsquo;t the dogs. It was the communication gap.
            </p>
            <p>
              We spent the first six months in a living room with five dogs, twelve
              biosensors, and a refrigerator full of training treats. The early models
              were embarrassing. Biscuit, our CEO&rsquo;s golden retriever, figured out how
              to game the reward system in under two hours. We considered it a success.
            </p>
            <p>
              Today, SuperPilot ships in 34 countries, has logged over 2 billion hours
              of canine behavioral data, and has helped more than 400,000 dogs
              graduate from their training programs. Biscuit still games the system
              occasionally. We&rsquo;ve made peace with that.
            </p>
          </div>
        </section>

        {/* Mission */}
        <section className="text-center">
          <p className="text-xs font-semibold uppercase tracking-widest mb-4" style={{ color: "#6c5ce7" }}>
            Mission
          </p>
          <blockquote
            className="text-3xl sm:text-4xl font-bold leading-tight max-w-2xl mx-auto"
            style={{ color: "#f0f0f8" }}
          >
            &ldquo;To bridge the communication gap between humans and their canine companions.&rdquo;
          </blockquote>
          <p className="mt-6 text-base leading-relaxed max-w-xl mx-auto" style={{ color: "#8888aa" }}>
            Dogs have been trying to tell us things for 15,000 years. We built the
            technology to finally start listening.
          </p>
        </section>

        {/* Divider */}
        <div style={{ borderTop: "1px solid rgba(108,92,231,0.15)" }} />

        {/* Team */}
        <section>
          <div className="mb-10 text-center">
            <p className="text-xs font-semibold uppercase tracking-widest mb-2" style={{ color: "#00cec9" }}>
              The Team
            </p>
            <h2 className="text-3xl font-bold" style={{ color: "#f0f0f8" }}>
              The humans behind the collars
            </h2>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
            {teamMembers.map((member) => (
              <article
                key={member.name}
                className="rounded-2xl p-6 flex flex-col gap-4"
                style={{
                  backgroundColor: "rgba(255,255,255,0.04)",
                  border: "1px solid rgba(108,92,231,0.15)",
                }}
              >
                <div className="flex items-center gap-4">
                  <div
                    className="w-12 h-12 rounded-full flex items-center justify-center text-sm font-bold flex-shrink-0"
                    style={{
                      backgroundColor: `${member.accent}22`,
                      color: member.accent,
                    }}
                  >
                    {member.initials}
                  </div>
                  <div>
                    <p className="font-semibold" style={{ color: "#f0f0f8" }}>
                      {member.name}
                    </p>
                    <p className="text-sm" style={{ color: "#8888aa" }}>
                      {member.title}
                    </p>
                  </div>
                </div>
                <div
                  className="rounded-xl px-4 py-3 text-sm leading-relaxed"
                  style={{
                    backgroundColor: "rgba(108,92,231,0.07)",
                    color: "#9999bb",
                  }}
                >
                  <span className="mr-1.5">🐾</span>
                  {member.dogFact}
                </div>
              </article>
            ))}
          </div>
        </section>

        {/* Divider */}
        <div style={{ borderTop: "1px solid rgba(108,92,231,0.15)" }} />

        {/* Values */}
        <section>
          <div className="mb-10 text-center">
            <p className="text-xs font-semibold uppercase tracking-widest mb-2" style={{ color: "#fd79a8" }}>
              Values
            </p>
            <h2 className="text-3xl font-bold" style={{ color: "#f0f0f8" }}>
              What we stand for
            </h2>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
            {values.map((value) => (
              <div
                key={value.title}
                className="rounded-2xl p-6 flex flex-col gap-3"
                style={{
                  backgroundColor: "rgba(255,255,255,0.04)",
                  border: "1px solid rgba(108,92,231,0.15)",
                }}
              >
                <div className="w-10 h-10 rounded-xl flex items-center justify-center"
                  style={{ backgroundColor: "rgba(108,92,231,0.08)" }}
                >
                  {value.icon}
                </div>
                <h3 className="font-semibold text-lg" style={{ color: "#f0f0f8" }}>
                  {value.title}
                </h3>
                <p className="text-sm leading-relaxed" style={{ color: "#8888aa" }}>
                  {value.description}
                </p>
              </div>
            ))}
          </div>
        </section>
      </main>

    </>
  );
}
