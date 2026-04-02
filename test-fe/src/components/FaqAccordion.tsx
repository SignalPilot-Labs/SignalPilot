'use client'

import { useState } from 'react'

interface FaqItem {
  question: string
  answer: string
}

interface FaqAccordionProps {
  items: FaqItem[]
}

export default function FaqAccordion({ items }: FaqAccordionProps) {
  const [openIndex, setOpenIndex] = useState<number | null>(null)

  return (
    <dl className="space-y-3">
      {items.map((item, index) => {
        const isOpen = openIndex === index

        return (
          <div
            key={index}
            className="rounded-xl border border-white/10 bg-white/5 overflow-hidden transition-colors hover:border-white/20"
          >
            <dt>
              <button
                type="button"
                aria-expanded={isOpen}
                aria-controls={`faq-answer-${index}`}
                id={`faq-question-${index}`}
                onClick={() => setOpenIndex(isOpen ? null : index)}
                className="flex w-full items-center justify-between gap-6 px-6 py-5 text-left"
              >
                <span className="text-base font-medium text-white">
                  {item.question}
                </span>
                <span
                  aria-hidden="true"
                  className={`flex-shrink-0 flex items-center justify-center w-6 h-6 rounded-full border border-white/20 text-indigo-300 transition-transform duration-200 ${isOpen ? 'rotate-45' : ''}`}
                >
                  <svg
                    width="12"
                    height="12"
                    viewBox="0 0 12 12"
                    fill="none"
                    xmlns="http://www.w3.org/2000/svg"
                  >
                    <path
                      d="M6 1V11M1 6H11"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                    />
                  </svg>
                </span>
              </button>
            </dt>
            <dd
              id={`faq-answer-${index}`}
              role="region"
              aria-labelledby={`faq-question-${index}`}
              hidden={!isOpen}
              className="px-6 pb-5"
            >
              <p className="text-sm leading-relaxed text-slate-400">
                {item.answer}
              </p>
            </dd>
          </div>
        )
      })}
    </dl>
  )
}
