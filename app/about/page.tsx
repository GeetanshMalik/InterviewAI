import { LandingLayout } from "@/layouts/landing-layout";
import { Footer } from "@/features/landing/footer";
import { FadeIn } from "@/components/animated-container";
import { Card } from "@/components/ui/card";
import { Database, Network, ShieldCheck } from "lucide-react";

const pillars = [
  {
    icon: Network,
    title: "Backend-owned orchestration",
    text: "InterviewAI routes interview generation, runtime progress, evaluation, reports, roadmaps, retries, and streams through backend workflow state.",
  },
  {
    icon: Database,
    title: "Memory that compounds",
    text: "Resume, transcript, weakness, roadmap, practice, and bot memories give agents useful context without making the frontend simulate intelligence.",
  },
  {
    icon: ShieldCheck,
    title: "Evidence and safety first",
    text: "Security, reviewer, and evaluation agents keep reports grounded in real round evidence and guard tool calls before they affect workflow state.",
  },
];

export default function AboutPage() {
  return (
    <LandingLayout>
      <div className="pt-32 pb-24">
        <FadeIn className="container mx-auto px-4">
          <div className="mx-auto max-w-3xl text-center">
            <h1 className="text-display-lg text-ink mb-6 tracking-tight">About InterviewAI</h1>
            <p className="text-subhead text-ink-muted leading-relaxed">
              InterviewAI is becoming an autonomous interview operating system:
              a backend-controlled multi-agent platform that generates, runs,
              evaluates, and improves technical interview preparation from real
              candidate evidence.
            </p>
          </div>

          <div className="mx-auto mt-14 grid max-w-6xl gap-6 md:grid-cols-3">
            {pillars.map((pillar) => {
              const Icon = pillar.icon;
              return (
                <Card key={pillar.title} className="border-hairline bg-surface-1 p-6">
                  <div className="mb-5 flex h-11 w-11 items-center justify-center rounded-lg border border-hairline bg-surface-2 text-accent-blue">
                    <Icon className="h-5 w-5" />
                  </div>
                  <h2 className="mb-3 text-headline text-ink">{pillar.title}</h2>
                  <p className="text-body-sm leading-relaxed text-ink-muted">{pillar.text}</p>
                </Card>
              );
            })}
          </div>
        </FadeIn>
      </div>
      <Footer />
    </LandingLayout>
  );
}
