const subjects = [
  "General Inquiry",
  "Partnership Opportunities",
  "Press & Media",
  "Technical Support",
  "Billing",
  "My dog gamed the reward system",
];

export default function ContactPage() {
  return (
    <>
      {/* Hero */}
      <header className="max-w-5xl mx-auto px-6 py-16 text-center">
        <div
          className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-medium mb-6"
          style={{ backgroundColor: "rgba(0,206,201,0.1)", color: "#00cec9" }}
        >
          <span
            className="w-1.5 h-1.5 rounded-full"
            style={{ backgroundColor: "#00cec9" }}
          />
          Get in Touch
        </div>
        <h1
          className="text-5xl font-bold tracking-tight mb-4"
          style={{ color: "#f0f0f8" }}
        >
          We&rsquo;d love to hear from you
        </h1>
        <p className="text-lg leading-relaxed max-w-xl mx-auto" style={{ color: "#8888aa" }}>
          Whether you&rsquo;re a dog owner, a potential partner, or just here because your dog sent you — we&rsquo;re listening.
        </p>
      </header>

      {/* Content */}
      <main className="max-w-5xl mx-auto px-6 pb-24">
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-10">
          {/* Contact form — spans 3 cols */}
          <section
            className="lg:col-span-3 rounded-2xl p-8"
            style={{
              backgroundColor: "rgba(255,255,255,0.04)",
              border: "1px solid rgba(108,92,231,0.2)",
            }}
          >
            <h2 className="text-xl font-semibold mb-6" style={{ color: "#f0f0f8" }}>
              Send us a message
            </h2>

            <form className="flex flex-col gap-5" noValidate>
              {/* Name + Email row */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
                <div className="flex flex-col gap-1.5">
                  <label
                    htmlFor="name"
                    className="text-sm font-medium"
                    style={{ color: "#b2b2cc" }}
                  >
                    Name
                  </label>
                  <input
                    id="name"
                    type="text"
                    placeholder="Your name"
                    className="rounded-xl px-4 py-2.5 text-sm outline-none transition-all"
                    style={{
                      backgroundColor: "rgba(255,255,255,0.06)",
                      border: "1px solid rgba(108,92,231,0.25)",
                      color: "#f0f0f8",
                    }}
                    readOnly
                  />
                </div>

                <div className="flex flex-col gap-1.5">
                  <label
                    htmlFor="email"
                    className="text-sm font-medium"
                    style={{ color: "#b2b2cc" }}
                  >
                    Email
                  </label>
                  <input
                    id="email"
                    type="email"
                    placeholder="you@example.com"
                    className="rounded-xl px-4 py-2.5 text-sm outline-none transition-all"
                    style={{
                      backgroundColor: "rgba(255,255,255,0.06)",
                      border: "1px solid rgba(108,92,231,0.25)",
                      color: "#f0f0f8",
                    }}
                    readOnly
                  />
                </div>
              </div>

              {/* Subject */}
              <div className="flex flex-col gap-1.5">
                <label
                  htmlFor="subject"
                  className="text-sm font-medium"
                  style={{ color: "#b2b2cc" }}
                >
                  Subject
                </label>
                <div className="relative">
                  <select
                    id="subject"
                    className="w-full appearance-none rounded-xl px-4 py-2.5 text-sm outline-none transition-all pr-10"
                    style={{
                      backgroundColor: "rgba(255,255,255,0.06)",
                      border: "1px solid rgba(108,92,231,0.25)",
                      color: "#f0f0f8",
                    }}
                    defaultValue=""
                    disabled
                  >
                    <option value="" disabled style={{ backgroundColor: "#1a1a2e" }}>
                      Select a subject
                    </option>
                    {subjects.map((s) => (
                      <option key={s} value={s} style={{ backgroundColor: "#1a1a2e" }}>
                        {s}
                      </option>
                    ))}
                  </select>
                  <svg
                    className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none"
                    width="16"
                    height="16"
                    viewBox="0 0 16 16"
                    fill="none"
                    aria-hidden="true"
                  >
                    <path
                      d="M4 6l4 4 4-4"
                      stroke="#8888aa"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </div>
              </div>

              {/* Message */}
              <div className="flex flex-col gap-1.5">
                <label
                  htmlFor="message"
                  className="text-sm font-medium"
                  style={{ color: "#b2b2cc" }}
                >
                  Message
                </label>
                <textarea
                  id="message"
                  rows={6}
                  placeholder="Tell us what's on your mind — or your dog's mind..."
                  className="rounded-xl px-4 py-2.5 text-sm outline-none transition-all resize-none"
                  style={{
                    backgroundColor: "rgba(255,255,255,0.06)",
                    border: "1px solid rgba(108,92,231,0.25)",
                    color: "#f0f0f8",
                  }}
                  readOnly
                />
              </div>

              {/* Submit */}
              <button
                type="button"
                className="inline-flex items-center justify-center gap-2 rounded-xl px-6 py-3 font-semibold text-sm transition-all hover:opacity-90 active:scale-95"
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
                    d="M2 8h12M8 3.5 12.5 8 8 12.5"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                Send Message
              </button>
            </form>
          </section>

          {/* Contact details — spans 2 cols */}
          <aside className="lg:col-span-2 flex flex-col gap-6">
            {/* Address */}
            <div
              className="rounded-2xl p-6 flex flex-col gap-4"
              style={{
                backgroundColor: "rgba(255,255,255,0.04)",
                border: "1px solid rgba(108,92,231,0.15)",
              }}
            >
              <h2 className="text-base font-semibold" style={{ color: "#f0f0f8" }}>
                Our Office
              </h2>
              <div className="flex flex-col gap-4">
                <ContactRow
                  icon={
                    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
                      <path
                        d="M9 1a5 5 0 0 1 5 5c0 3.5-5 11-5 11S4 9.5 4 6a5 5 0 0 1 5-5Z"
                        fill="#6c5ce7"
                        opacity="0.15"
                        stroke="#6c5ce7"
                        strokeWidth="1.3"
                      />
                      <circle cx="9" cy="6" r="1.5" fill="#6c5ce7" />
                    </svg>
                  }
                  label="Address"
                  value="123 Bark Avenue, San Francisco, CA 94102"
                />
                <ContactRow
                  icon={
                    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
                      <rect x="2" y="4" width="14" height="10" rx="2" fill="#00cec9" opacity="0.12" stroke="#00cec9" strokeWidth="1.3" />
                      <path d="m2 4 7 6 7-6" stroke="#00cec9" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  }
                  label="Email"
                  value="hello@superpilot.ai"
                  href="mailto:hello@superpilot.ai"
                />
                <ContactRow
                  icon={
                    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
                      <path
                        d="M4 2a1 1 0 0 0-1 1v1.5c0 .83.1 1.63.29 2.4A13 13 0 0 0 11.1 14.7c.77.19 1.57.3 2.4.3H15a1 1 0 0 0 1-1v-1.5a1 1 0 0 0-.78-.97l-2-.47a1 1 0 0 0-1.06.46l-.6 1a8 8 0 0 1-3.08-3.08l1-.6a1 1 0 0 0 .46-1.06l-.47-2A1 1 0 0 0 8.5 5H4Z"
                        fill="#fd79a8"
                        opacity="0.15"
                        stroke="#fd79a8"
                        strokeWidth="1.3"
                      />
                    </svg>
                  }
                  label="Phone"
                  value="(555) DOG-AI00"
                  href="tel:+15553642400"
                />
                <ContactRow
                  icon={
                    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
                      <circle cx="9" cy="9" r="7" fill="#6c5ce7" opacity="0.1" stroke="#6c5ce7" strokeWidth="1.3" />
                      <path d="M9 5v4l2.5 2.5" stroke="#6c5ce7" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  }
                  label="Office Hours"
                  value="Mon–Fri 9am–6pm PST"
                  note="(we're flexible, like our dogs)"
                />
              </div>
            </div>

            {/* Quick note */}
            <div
              className="rounded-2xl px-6 py-5 flex items-start gap-3"
              style={{
                backgroundColor: "rgba(108,92,231,0.07)",
                border: "1px solid rgba(108,92,231,0.2)",
              }}
            >
              <span className="text-xl mt-0.5" aria-hidden="true">🐾</span>
              <p className="text-sm leading-relaxed" style={{ color: "#9999bb" }}>
                We typically respond within one business day. If your dog is
                involved in the inquiry, responses may arrive faster — our team
                has a soft spot.
              </p>
            </div>
          </aside>
        </div>
      </main>

    </>
  );
}

function ContactRow({
  icon,
  label,
  value,
  href,
  note,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  href?: string;
  note?: string;
}) {
  return (
    <div className="flex items-start gap-3">
      <div
        className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5"
        style={{ backgroundColor: "rgba(108,92,231,0.08)" }}
      >
        {icon}
      </div>
      <div className="flex flex-col gap-0.5">
        <p className="text-xs font-medium uppercase tracking-wider" style={{ color: "#55556a" }}>
          {label}
        </p>
        {href ? (
          <a
            href={href}
            className="text-sm transition-colors hover:text-white"
            style={{ color: "#b2b2cc" }}
          >
            {value}
          </a>
        ) : (
          <p className="text-sm" style={{ color: "#b2b2cc" }}>
            {value}
          </p>
        )}
        {note && (
          <p className="text-xs" style={{ color: "#55556a" }}>
            {note}
          </p>
        )}
      </div>
    </div>
  );
}
