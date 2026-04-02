import { ArrowRightIcon, PlayIcon } from "./icons";
import { PawPrint } from "./PawPrint";

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

export default function HeroSection() {
  return (
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
  );
}
