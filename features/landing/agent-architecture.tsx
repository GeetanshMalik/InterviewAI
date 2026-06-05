"use client";

import { motion } from "framer-motion";
import {
  Bot,
  Brain,
  ClipboardCheck,
  Code,
  Database,
  FileText,
  Map,
  Network,
  Route,
  ShieldCheck,
  Target,
  UserCheck,
} from "lucide-react";
import { FadeIn, StaggerContainer, StaggerItem } from "@/components/animated-container";
import { cn } from "@/lib/utils";

const agents = [
  {
    icon: FileText,
    name: "Resume Agent",
    description: "Normalizes resume and role context into a structured candidate profile.",
    color: "from-gradient-violet to-accent-blue"
  },
  {
    icon: Route,
    name: "Planning Agent",
    description: "Builds interview strategy from role, difficulty, resume, and memory signals.",
    color: "from-gradient-magenta to-gradient-coral"
  },
  {
    icon: Code,
    name: "DSA Agent",
    description: "Generates coding problems and evaluates execution, complexity, and code quality.",
    color: "from-gradient-orange to-amber-500"
  },
  {
    icon: Target,
    name: "Aptitude Agent",
    description: "Creates reasoning questions and scores accuracy with per-question evidence.",
    color: "from-emerald-400 to-teal-500"
  },
  {
    icon: Brain,
    name: "Technical Agent",
    description: "Runs adaptive technical questions and follow-up decisions from backend state.",
    color: "from-cyan-400 to-blue-500"
  },
  {
    icon: UserCheck,
    name: "HR Agent",
    description: "Evaluates communication, behavioral evidence, and interview confidence.",
    color: "from-pink-400 to-rose-500"
  },
  {
    icon: ClipboardCheck,
    name: "Evaluation Agent",
    description: "Applies rubric scoring and records safe reasoning traces for downstream agents.",
    color: "from-violet-400 to-indigo-500"
  },
  {
    icon: Bot,
    name: "Report Agent",
    description: "Converts round evidence into a candidate-facing report without inventing facts.",
    color: "from-sky-400 to-cyan-500"
  },
  {
    icon: Map,
    name: "Roadmap Agent",
    description: "Turns weakness history into focused learning milestones and practice plans.",
    color: "from-lime-400 to-emerald-500"
  },
  {
    icon: Database,
    name: "Memory Agent",
    description: "Retrieves and writes semantic memory under privacy and usefulness controls.",
    color: "from-emerald-400 to-teal-500"
  },
  {
    icon: ShieldCheck,
    name: "Security Agent",
    description: "Sanitizes inputs, quarantines unsafe content, and guards tool execution.",
    color: "from-amber-400 to-orange-500"
  },
  {
    icon: Network,
    name: "Workflow Orchestrator",
    description: "Routes agents, jobs, retries, streams, checkpoints, and completion decisions.",
    color: "from-indigo-400 to-purple-500"
  },
];

export function AgentArchitecture() {
  return (
    <section className="relative overflow-visible border-y border-hairline bg-surface-1/50 py-24">
      <div className="container mx-auto px-4">
        <FadeIn>
          <div className="text-center max-w-3xl mx-auto mb-16">
            <h2 className="text-display-lg text-ink mb-6 tracking-tight">The Neural Engine</h2>
            <p className="text-subhead text-ink-muted">
              InterviewAI now coordinates 12+ specialized backend agents through shared state, tools, memory, critique loops, and workflow events.
            </p>
          </div>
        </FadeIn>

        <div className="relative max-w-6xl mx-auto mt-16">
          {/* Central Hub */}
          <div className="mb-10 flex justify-center">
            <motion.div
              animate={{ boxShadow: ["0 0 0px 0px rgba(106, 76, 245, 0.4)", "0 0 40px 10px rgba(106, 76, 245, 0)"] }}
              transition={{ duration: 2, repeat: Infinity }}
              className="w-24 h-24 rounded-full bg-surface-2 border border-hairline flex items-center justify-center relative shadow-2xl"
            >
              <div className="absolute inset-0 rounded-full bg-gradient-to-tr from-gradient-violet to-gradient-magenta opacity-20" />
              <Network className="w-10 h-10 text-ink" />
            </motion.div>
          </div>

          <StaggerContainer className="relative z-10 grid grid-cols-1 items-stretch gap-8 md:grid-cols-2 xl:grid-cols-3">
            {agents.map((agent, index) => (
              <StaggerItem key={index}>
                <div className={cn(
                  "group h-full min-h-[160px] rounded-lg border border-hairline bg-surface-1 p-6 transition-colors duration-300 hover:border-hairline-soft"
                )}>
                  <div className="flex items-start gap-4">
                    <div className={cn("shrink-0 rounded-lg bg-gradient-to-br p-3", agent.color, "bg-opacity-10")}>
                      <agent.icon className="w-6 h-6 text-ink" />
                    </div>
                    <div className="min-w-0">
                      <h3 className="mb-2 text-headline text-ink transition-colors duration-300 group-hover:text-ink">
                        {agent.name}
                      </h3>
                      <p className="text-body-sm text-ink-muted leading-relaxed">
                        {agent.description}
                      </p>
                    </div>
                  </div>
                </div>
              </StaggerItem>
            ))}
          </StaggerContainer>
        </div>
      </div>
    </section>
  );
}
