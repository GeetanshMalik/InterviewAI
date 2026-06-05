"use client";

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { FadeIn, StaggerContainer, StaggerItem } from "@/components/animated-container";

const faqs = [
  {
    question: "How is this different from LeetCode?",
    answer: "LeetCode tests your ability to pass unit tests. InterviewAI tests your ability to communicate your thought process, adapt to constraints dynamically provided by the interviewer, and handle behavioral questions—exactly like a real FAANG interview."
  },
  {
    question: "Do the agents use voice?",
    answer: "Yes. Our multi-agent system features low-latency voice synthesis to create a conversational, real-time interview environment. You can speak naturally, and the agent will respond, interrupt, or pivot based on your answers."
  },
  {
    question: "Can I practice System Design?",
    answer: "Absolutely. Our System Design Architect agent can present you with ambiguous problems (e.g., 'Design Twitter') and will critically evaluate your choices regarding databases, scaling, caching, and load balancing."
  },
  {
    question: "What companies are the evaluations calibrated for?",
    answer: "Our evaluation metrics are calibrated against the rubrics of top-tier tech companies (Meta, Google, Amazon, Apple, Netflix) and top startups. We focus on code efficiency, system scalability, and leadership principles."
  }
];

export function FaqSection() {
  return (
    <section className="py-32 relative bg-surface-1/30">
      <div className="container mx-auto px-4 max-w-3xl">
        <FadeIn>
          <div className="text-center mb-16">
            <h2 className="text-display-lg text-ink mb-6 tracking-tight">Common Questions</h2>
            <p className="text-subhead text-ink-muted">
              Everything you need to know about the platform.
            </p>
          </div>
        </FadeIn>

        <StaggerContainer>
          <Accordion type="single" collapsible className="w-full space-y-4">
            {faqs.map((faq, i) => (
              <StaggerItem key={i}>
                <AccordionItem value={`item-${i}`} className="bg-surface-1 border border-hairline rounded-xl px-6 data-[state=open]:border-hairline-soft transition-colors">
                  <AccordionTrigger className="text-headline text-ink hover:no-underline py-6 text-left">
                    {faq.question}
                  </AccordionTrigger>
                  <AccordionContent className="text-body text-ink-muted pb-6 leading-relaxed">
                    {faq.answer}
                  </AccordionContent>
                </AccordionItem>
              </StaggerItem>
            ))}
          </Accordion>
        </StaggerContainer>
      </div>
    </section>
  );
}
