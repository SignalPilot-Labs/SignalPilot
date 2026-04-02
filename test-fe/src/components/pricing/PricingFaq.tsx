import FaqAccordion from '@/components/FaqAccordion'

interface FaqItem {
  question: string
  answer: string
}

const faqs: FaqItem[] = [
  {
    question: 'Can I change my plan at any time?',
    answer:
      'Yes. You can upgrade, downgrade, or cancel your subscription at any time from your account settings. When upgrading, the change takes effect immediately and you are billed the prorated difference. When downgrading, the change takes effect at the end of your current billing period.',
  },
  {
    question: 'Is there a free trial for paid plans?',
    answer:
      'The Good Boy Plan includes a 14-day free trial — no credit card required. If you decide it is not right for you, simply cancel before the trial ends and you will never be charged. The Alpha Pack plan offers a personalized demo; contact our sales team to get started.',
  },
  {
    question: 'What happens to my data if I cancel?',
    answer:
      'Your dog profiles, activity history, and training records are retained for 30 days after cancellation, giving you time to export everything. After 30 days, data is permanently deleted in accordance with our privacy policy.',
  },
  {
    question: 'Do you offer discounts for annual billing?',
    answer:
      'Yes. Choosing annual billing saves you two months compared to monthly — effectively giving you 12 months for the price of 10. Annual plans are available for both the Good Boy and Alpha Pack tiers and can be selected during signup or from your account settings.',
  },
  {
    question: 'Can I add more dogs beyond my plan limit?',
    answer:
      'On the Good Boy Plan you can have up to 3 dog profiles. If your pack keeps growing, upgrading to Alpha Pack gives you unlimited profiles. You can also temporarily add an extra profile by contacting support, and we will work out the best option for your situation.',
  },
]

export default function PricingFaq() {
  return (
    <section
      aria-labelledby="faq-heading"
      className="mx-auto max-w-3xl px-6 pb-32"
    >
      <div className="text-center mb-12">
        <h2
          id="faq-heading"
          className="text-3xl font-bold tracking-tight text-white"
        >
          Frequently asked questions
        </h2>
        <p className="mt-3 text-slate-400">
          Can&apos;t find the answer you&apos;re looking for?{' '}
          <a
            href="/contact"
            className="text-indigo-400 underline underline-offset-2 hover:text-indigo-300 transition-colors"
          >
            Reach out to our team
          </a>
          .
        </p>
      </div>

      <FaqAccordion items={faqs} />
    </section>
  )
}
