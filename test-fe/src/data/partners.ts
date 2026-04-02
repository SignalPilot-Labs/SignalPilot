export interface Partner {
  name: string;
  slug: string;
  emoji: string;
  tagline: string;
  description: string;
  founded: number;
  headquarters: string;
  category: string;
  keyFeatures: string[];
  integrationDescription: string;
}

export const partners: Partner[] = [
  {
    name: "PawTech Labs",
    slug: "pawtech-labs",
    emoji: "📡",
    tagline: "Pioneering wearable tech for pets since 2022",
    category: "Hardware",
    description:
      "PawTech Labs designs and manufactures the smart collars that power SuperPilot's real-time behavioral data pipeline. Their ultra-low-power sensors capture heart rate, movement patterns, and vocalizations with veterinary-grade accuracy. Every collar ships with a five-year battery life and military-spec waterproofing — because dogs don't check the weather forecast.",
    founded: 2022,
    headquarters: "Austin, TX",
    keyFeatures: [
      "Sub-milliwatt biosensor array capturing 14 physiological signals simultaneously",
      "Edge-AI chip that runs SuperPilot inference on-device with zero cloud latency",
      "Haptic feedback motor for real-time reward pulses triggered by good behavior",
    ],
    integrationDescription:
      "PawTech collars communicate directly with the SuperPilot mobile app over BLE 5.3. Firmware updates are delivered OTA, and raw sensor streams are securely forwarded to the SuperPilot cloud for model training — with owner consent required at every step.",
  },
  {
    name: "BarkCloud",
    slug: "barkcloud",
    emoji: "☁️",
    tagline: "Scalable cloud computing for pet AI workloads",
    category: "Infrastructure",
    description:
      "BarkCloud is the managed cloud platform purpose-built for the unique demands of pet AI — bursty inference, massive sensor telemetry, and the occasional 3 AM emergency health alert. They operate eight globally distributed data centers and maintain a 99.999% uptime SLA. Their engineering team includes more dog owners per capita than any Fortune 500 company.",
    founded: 2021,
    headquarters: "Seattle, WA",
    keyFeatures: [
      "Pet-AI-optimized GPU clusters with custom CUDA kernels for behavioral model inference",
      "Zero-copy telemetry ingestion pipeline handling 10 billion sensor events per day",
      "Automatic regional failover that keeps health alerts flowing even during outages",
    ],
    integrationDescription:
      "All SuperPilot model training, inference serving, and long-term sensor storage run on BarkCloud infrastructure. Their dedicated SuperPilot tenant is isolated at the hardware level, and all data at rest is encrypted with customer-managed keys.",
  },
  {
    name: "VetAI Inc.",
    slug: "vetai-inc",
    emoji: "🩺",
    tagline: "AI-assisted diagnostics for veterinary professionals",
    category: "Veterinary AI",
    description:
      "VetAI Inc. builds clinical-grade diagnostic models trained on the world's largest annotated dataset of canine medical records — over 40 million cases across 312 breeds. Their models power the health-alert layer inside SuperPilot, surfacing early warning signs that a dog's own human might miss. All outputs are reviewed by a board of licensed veterinary internists before being incorporated into the platform.",
    founded: 2020,
    headquarters: "Boston, MA",
    keyFeatures: [
      "Multi-modal diagnostic engine combining collar biometrics, owner-reported symptoms, and breed baselines",
      "Regulatory-grade explainability reports generated for every health alert",
      "24/7 veterinary triage hotline available to SuperPilot Premium subscribers",
    ],
    integrationDescription:
      "SuperPilot pipes anonymized sensor streams into VetAI's HIPAA-compliant inference API in real time. When VetAI's models detect an anomaly above a configurable confidence threshold, SuperPilot surfaces an in-app alert and, where appropriate, connects the owner directly to a licensed vet via the VetAI telehealth portal.",
  },
  {
    name: "Treat.io",
    slug: "treat-io",
    emoji: "🦴",
    tagline: "IoT-connected treat dispensing, triggered by good behavior",
    category: "IoT Hardware",
    description:
      "Treat.io makes the world's most satisfying smart treat dispensers — precision-engineered to fire a treat within 300 milliseconds of a good-behavior signal, the narrowest reinforcement window in the industry. Their dispensers support 47 treat types, have a tamper-proof hopper that holds a full pound of kibble, and come in colors that match any interior design aesthetic. Yes, including mid-century modern.",
    founded: 2023,
    headquarters: "Portland, OR",
    keyFeatures: [
      "Sub-300ms treat delivery latency for scientifically optimal positive reinforcement timing",
      "Computer-vision lid that verifies the dog is in position before dispensing",
      "Auto-refill subscription service with breed-specific nutritionist-approved treat packs",
    ],
    integrationDescription:
      "Treat.io dispensers register as first-class SuperPilot devices. When the SuperPilot AI detects a trained behavior being performed correctly, it dispatches a signed dispense command to the nearest Treat.io unit on the same Wi-Fi network — no owner input required. Owners can review every dispense event in the SuperPilot timeline.",
  },
  {
    name: "WoofWorks",
    slug: "woofworks",
    emoji: "🎓",
    tagline: "Professional dog trainers creating AI-enhanced curricula",
    category: "Training Content",
    description:
      "WoofWorks is a collective of over 200 certified professional dog trainers who author, film, and quality-assure every piece of training content inside SuperPilot. They combine decades of applied behavior analysis expertise with modern AI tooling to produce curricula that adapt in real time to each individual dog's learning pace, breed tendencies, and personality quirks. No two training plans look the same.",
    founded: 2019,
    headquarters: "Denver, CO",
    keyFeatures: [
      "Adaptive curriculum engine that re-sequences lessons based on live SuperPilot behavioral scores",
      "Video library of 3,000+ trainer-filmed demonstrations covering 180 distinct behaviors",
      "Certified Trainer Chat — live text access to a WoofWorks trainer, included with SuperPilot Pro",
    ],
    integrationDescription:
      "WoofWorks content is embedded natively in the SuperPilot app as interactive training sessions. The SuperPilot AI monitors session progress in real time and can call the WoofWorks curriculum API mid-session to swap in a simpler or more challenging exercise based on the dog's current performance metrics.",
  },
  {
    name: "FurFinance",
    slug: "furfinance",
    emoji: "💳",
    tagline: "AI-powered pet insurance that actually pays out",
    category: "Pet Insurance",
    description:
      "FurFinance threw out the traditional pet insurance playbook and rebuilt underwriting from scratch using real behavioral and biometric data. Because they have access (with owner consent) to longitudinal SuperPilot health data, they can price policies more accurately, identify risks earlier, and process claims in under four hours. Their denial rate is 94% lower than the industry average — a statistic they put in every ad.",
    founded: 2022,
    headquarters: "New York, NY",
    keyFeatures: [
      "Dynamic premium pricing that rewards healthy behavior tracked by SuperPilot — premiums can go down",
      "Automated claims processing powered by VetAI diagnostic data with average 3.8-hour payout",
      "Breed-specific coverage riders that cover conditions statistically predicted by the dog's SuperPilot profile",
    ],
    integrationDescription:
      "SuperPilot owners can link their FurFinance policy in-app with a single tap. Consented health data flows to FurFinance's underwriting API on a rolling 30-day basis, enabling real-time premium adjustments. When VetAI raises a health alert, FurFinance is notified simultaneously and pre-stages the claims flow before the owner even books a vet appointment.",
  },
];

export function getPartnerBySlug(slug: string): Partner | undefined {
  return partners.find((p) => p.slug === slug);
}
