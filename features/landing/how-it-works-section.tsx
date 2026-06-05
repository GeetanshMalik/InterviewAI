"use client";

import { SpotlightCard } from "@/components/gradient-card";
import { StaggerContainer, StaggerItem } from "@/components/animated-container";
import { FileText, Code2, MessageSquare, BarChart3 } from "lucide-react";

const steps = [
  {
    number: "01",
    icon: FileText,
    title: "Submit Your Profile",
    description:
      "Upload your resume, select target role and company style. Our AI analyzes your background to customize the interview experience.",
  },
  {
    number: "02",
    icon: Code2,
    title: "Complete Multi-Round Interview",
    description:
      "Go through DSA coding, aptitude tests, technical interviews, and HR rounds. Each powered by specialized AI agents.",
  },
  {
    number: "03",
    icon: BarChart3,
    title: "Receive Detailed Analysis",
    description:
      "Get comprehensive reports with scores, transcripts, strengths, weaknesses, and AI-powered feedback on every aspect.",
  },
  {
    number: "04",
    icon: MessageSquare,
    title: "Follow Your Roadmap",
    description:
      "Access personalized learning paths, practice recommendations, and continuous improvement tracking with AI guidance.",
  },
];

export function HowItWorksSection() {
  return (
    <section className="py-section bg-surface-1/30">
      <div className="container mx-auto px-4">
        <div className="text-center mb-16">
          <h2 className="text-display-lg text-ink mb-4">How It Works</h2>
          <p className="text-subhead text-ink-muted max-w-2xl mx-auto">
            A streamlined workflow designed to maximize your interview preparation
            efficiency.
          </p>
        </div>

        <StaggerContainer className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {steps.map((step, index) => (
            <StaggerItem key={index}>
              <SpotlightCard className="h-full">
                <div className="text-caption text-accent-blue font-bold mb-4">
                  {step.number}
                </div>
                <step.icon className="w-8 h-8 text-ink mb-4" />
                <h3 className="text-headline text-ink mb-2">{step.title}</h3>
                <p className="text-body text-ink-muted">{step.description}</p>
              </SpotlightCard>
            </StaggerItem>
          ))}
        </StaggerContainer>
      </div>
    </section>
  );
}
