"use client";

import { Bot, CheckCircle2, Code2, Database, FileText, LayoutDashboard, Zap } from "lucide-react";
import { FadeIn, StaggerContainer, StaggerItem } from "@/components/animated-container";

const features = [
  {
    icon: Zap,
    title: "Backend-Controlled Adaptive Interviews",
    description: "The orchestrator owns the interview state, allowed actions, retries, and next-round decisions while the frontend renders the current workflow."
  },
  {
    icon: Code2,
    title: "Real Code Execution",
    description: "DSA answers run through Judge0 or the local runner fallback, then feed rubric scoring, edge-case evidence, and code-quality feedback."
  },
  {
    icon: Database,
    title: "Semantic Memory",
    description: "Resume, report, transcript, weakness, roadmap, practice, and bot memories are retrieved by agents so new sessions build on prior evidence."
  },
  {
    icon: Bot,
    title: "Collaborative Agent Graph",
    description: "Planning, critic, security, evaluator, report, roadmap, practice, and memory agents communicate through shared state and tool results."
  },
  {
    icon: FileText,
    title: "Evidence-Based Reports",
    description: "Final reports and roadmaps are generated through the lifecycle graph and checked against round performance before they are saved."
  },
  {
    icon: LayoutDashboard,
    title: "Synced Analytics",
    description: "Dashboards track only completed, report-backed interviews, keeping score and confidence trends aligned with successful interview outcomes."
  }
];

export function FeaturesSection() {
  return (
    <section className="py-32 relative">
      <div className="container mx-auto px-4">
        <FadeIn>
          <div className="text-center max-w-3xl mx-auto mb-20">
            <h2 className="text-display-lg text-ink mb-6 tracking-tight">Beyond Mock Interviews</h2>
            <p className="text-subhead text-ink-muted">
              We've engineered an end-to-end career intelligence platform built for modern software engineers.
            </p>
          </div>
        </FadeIn>

        <StaggerContainer className="grid md:grid-cols-2 xl:grid-cols-3 gap-8">
          {features.map((feature, i) => (
            <StaggerItem key={i}>
              <div className="bg-surface-1 border border-hairline p-8 rounded-2xl h-full hover:-translate-y-1 transition-transform duration-300">
                <div className="w-12 h-12 rounded-xl bg-surface-2 flex items-center justify-center mb-6 border border-hairline">
                  <feature.icon className="w-6 h-6 text-accent-blue" />
                </div>
                <h3 className="text-headline text-ink mb-4">{feature.title}</h3>
                <p className="text-body text-ink-muted leading-relaxed">
                  {feature.description}
                </p>
              </div>
            </StaggerItem>
          ))}
        </StaggerContainer>

        <div className="mt-32 max-w-5xl mx-auto bg-surface-1 border border-hairline rounded-3xl p-8 md:p-12 overflow-hidden relative">
          <div className="absolute top-0 right-0 w-1/2 h-full bg-gradient-to-l from-surface-2 to-transparent pointer-events-none" />
          
          <div className="grid md:grid-cols-2 gap-12 items-center relative z-10">
            <div>
              <h3 className="text-display-md text-ink mb-6">Strict standards. <br/>Zero compromise.</h3>
              <ul className="space-y-4">
                {[
                  "LangGraph workflow orchestration",
                  "Live workflow and agent events",
                  "Tool-grounded DSA evaluation",
                  "Resume-aware question generation"
                ].map((item, i) => (
                  <li key={i} className="flex items-center gap-3 text-body text-ink-muted">
                    <CheckCircle2 className="w-5 h-5 text-accent-blue shrink-0" />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
            
            <div className="relative h-64 md:h-full min-h-[300px] bg-surface-2 rounded-xl border border-hairline overflow-hidden flex items-center justify-center">
              {/* Dummy UI representation */}
              <div className="absolute inset-4 rounded-lg bg-canvas border border-hairline shadow-2xl p-4 flex flex-col gap-4">
                <div className="h-8 w-1/3 bg-surface-1 rounded" />
                <div className="h-4 w-full bg-surface-1 rounded" />
                <div className="h-4 w-5/6 bg-surface-1 rounded" />
                <div className="mt-auto flex gap-2">
                  <div className="h-6 w-16 bg-gradient-violet rounded" />
                  <div className="h-6 w-16 bg-gradient-magenta rounded" />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
