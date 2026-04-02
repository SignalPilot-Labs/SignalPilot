import { StarIcon } from "./icons";

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

function StarRating({ count = 5 }: { count?: number }) {
  return (
    <div className="flex gap-0.5 text-amber-400" role="img" aria-label={`${count} out of 5 stars`}>
      {Array.from({ length: 5 }, (_, i) => (
        <StarIcon key={i} filled={i < count} />
      ))}
    </div>
  );
}

export default function TestimonialsSection() {
  return (
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
  );
}
