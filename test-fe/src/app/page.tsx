import Link from "next/link";
import { PawPrint } from "@/components/landing/PawPrint";
import HeroSection from "@/components/landing/HeroSection";
import FeaturesSection from "@/components/landing/FeaturesSection";
import TestimonialsSection from "@/components/landing/TestimonialsSection";
import PartnersPreview from "@/components/landing/PartnersPreview";
import CtaSection from "@/components/landing/CtaSection";

export default function Home() {
  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 font-sans">

      <header className="relative z-20 flex items-center justify-between px-6 py-5 max-w-7xl mx-auto">
        <div className="flex items-center gap-2">
          <PawPrint className="w-7 h-7 text-amber-400" />
          <span className="text-xl font-bold tracking-tight text-white">
            Super<span className="text-amber-400">Pilot</span>
          </span>
        </div>
        <nav className="hidden md:flex items-center gap-8 text-sm text-zinc-400">
          <a href="#features" className="hover:text-white transition-colors">Features</a>
          <a href="#testimonials" className="hover:text-white transition-colors">Reviews</a>
          <Link href="/partners" className="hover:text-white transition-colors">Partners</Link>
        </nav>
        <a
          href="#signup"
          className="text-sm font-semibold bg-amber-400 text-zinc-900 px-4 py-2 rounded-full hover:bg-amber-300 transition-colors"
        >
          Get Started
        </a>
      </header>

      <main>
        <HeroSection />
        <FeaturesSection />
        <TestimonialsSection />
        <PartnersPreview />
        <CtaSection />
      </main>

      <footer className="border-t border-zinc-800 py-10 px-6">
        <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4 text-sm text-zinc-500">
          <div className="flex items-center gap-2">
            <PawPrint className="w-5 h-5 text-amber-400" />
            <span className="font-semibold text-white">
              Super<span className="text-amber-400">Pilot</span>
            </span>
          </div>
          <p>&copy; {new Date().getFullYear()} SuperPilot. All rights reserved.</p>
          <nav className="flex gap-6" aria-label="Footer navigation">
            <a href="#" className="hover:text-zinc-300 transition-colors">Privacy</a>
            <a href="#" className="hover:text-zinc-300 transition-colors">Terms</a>
            <Link href="/partners" className="hover:text-zinc-300 transition-colors">Partners</Link>
          </nav>
        </div>
      </footer>

    </div>
  );
}
