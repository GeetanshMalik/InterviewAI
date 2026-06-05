"use client";

import { useEffect, useMemo, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useInterviewStore } from "@/stores/interview-store";
import { useSettingsStore } from "@/stores/settings-store";
import { cleanGeneratedText } from "@/lib/generated-text";
import { cn } from "@/lib/utils";
import { Activity, GitBranch, Terminal, Users } from "lucide-react";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function numericValue(value: unknown) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function arrayCount(value: unknown) {
  return Array.isArray(value) ? value.length : 0;
}

function explicitCount(value: unknown, fallback: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  const numericFallback = numericValue(fallback);
  return numericFallback > 0 ? numericFallback : arrayCount(fallback);
}

export function ExecutionLogPanel() {
  const { executionLogs, workflowState, dsaProblems, aptitudeQuestions, technicalQuestions, hrQuestions } = useInterviewStore();
  const showExecutionLogs = useSettingsStore((state) => state.settings.interview.showExecutionLogs);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const visibleLogs = useMemo(() => executionLogs.slice(-300), [executionLogs]);
  const orchestrationSummary = useMemo(() => {
    const orchestration = workflowState?.orchestration;
    const result = asRecord(workflowState?.job?.result);
    const workflow = asRecord(result.workflow_state);
    const agents = new Set(visibleLogs.map((log) => cleanGeneratedText(log.agent)).filter(Boolean));
    const criticLogCount = visibleLogs.filter((log) => {
      const text = `${cleanGeneratedText(log.agent)} ${cleanGeneratedText(log.message)}`.toLowerCase();
      return text.includes("critic") || text.includes("critique") || text.includes("reviewer");
    }).length;
    const planningCritiques = explicitCount(orchestration?.planningCritiqueCount ?? workflow.planning_critique_count, workflow.planning_critiques);
    const reviewerCritiques = explicitCount(orchestration?.reviewerCritiqueCount ?? workflow.reviewer_critique_count, workflow.reviewer_critiques);
    const sectionReviews = explicitCount(orchestration?.sectionReviewCount ?? workflow.section_review_count, workflow.section_generation_reviews);
    const totalCritiques = Math.max(planningCritiques + reviewerCritiques + sectionReviews, criticLogCount);
    const proofArtifacts = orchestration?.artifactCounts;
    const artifacts = {
      dsa: Math.max(proofArtifacts?.dsa || 0, arrayCount(result.dsa_problems), dsaProblems.length),
      aptitude: Math.max(proofArtifacts?.aptitude || 0, arrayCount(result.aptitude_questions), aptitudeQuestions.length),
      technical: Math.max(proofArtifacts?.technical || 0, arrayCount(result.technical_questions), technicalQuestions.length),
      hr: Math.max(proofArtifacts?.hr || 0, arrayCount(result.hr_questions), hrQuestions.length),
    };
    return {
      node: orchestration?.currentNode || workflowState?.job?.currentNode || "form",
      status: workflowState?.job?.status || "ready",
      agents: orchestration?.agentCount || agents.size,
      tools: orchestration?.toolDecisionCount ?? Number(workflow.tool_decision_count || 0),
      critiques: totalCritiques,
      artifacts,
    };
  }, [aptitudeQuestions.length, dsaProblems.length, hrQuestions.length, technicalQuestions.length, visibleLogs, workflowState]);

  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;
    container.scrollTop = container.scrollHeight;
  }, [executionLogs.length]);

  const lineTone = (type: string) => {
    switch (type) {
      case "success":
        return "text-semantic-success";
      case "error":
        return "text-gradient-orange";
      case "warning":
        return "text-gradient-coral";
      default:
        return "text-accent-blue";
    }
  };

  if (!showExecutionLogs) {
    return null;
  }

  return (
    <Card className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden border border-accent-blue/40 bg-[#070909] p-0 ring-1 ring-accent-blue/35">
      <CardHeader className="flex min-w-0 flex-row items-center gap-3 border-b border-white/10 px-5 py-4">
        <Terminal className="h-4 w-4 text-semantic-success" />
        <CardTitle className="min-w-0 truncate text-body-sm font-semibold uppercase tracking-wide text-ink">
          Execution Logs
        </CardTitle>
      </CardHeader>
      <CardContent className="min-h-0 flex flex-1 flex-col px-0 pb-0">
        {workflowState && (
          <div className="space-y-3 border-b border-white/10 px-5 py-4">
            <div className="grid grid-cols-1 gap-2 text-[11px] leading-4 text-ink-muted sm:grid-cols-2">
              <div className="flex min-w-0 items-center gap-2 rounded-md border border-white/10 bg-white/[0.03] px-3 py-2">
                <GitBranch className="h-3.5 w-3.5 shrink-0 text-accent-blue" />
                <div className="min-w-0">
                  <p className="text-micro uppercase text-ink-muted">Node</p>
                  <p className="truncate text-caption text-ink">{orchestrationSummary.node}</p>
                </div>
              </div>
              <div className="flex min-w-0 items-center gap-2 rounded-md border border-white/10 bg-white/[0.03] px-3 py-2">
                <Activity className="h-3.5 w-3.5 shrink-0 text-semantic-success" />
                <div className="min-w-0">
                  <p className="text-micro uppercase text-ink-muted">Status</p>
                  <p className="truncate text-caption text-ink">{orchestrationSummary.status}</p>
                </div>
              </div>
              <div className="flex min-w-0 items-center gap-2 rounded-md border border-white/10 bg-white/[0.03] px-3 py-2">
                <Users className="h-3.5 w-3.5 shrink-0 text-gradient-coral" />
                <div className="min-w-0">
                  <p className="text-micro uppercase text-ink-muted">Agents</p>
                  <p className="truncate text-caption text-ink">{orchestrationSummary.agents} observed</p>
                </div>
              </div>
              <div className="min-w-0 rounded-md border border-white/10 bg-white/[0.03] px-3 py-2">
                <p className="text-micro uppercase text-ink-muted">Reasoning</p>
                <p className="truncate text-caption text-ink">
                  {orchestrationSummary.tools} tools / {orchestrationSummary.critiques} critiques
                </p>
              </div>
            </div>
            {orchestrationSummary.artifacts && (
              <div className="grid grid-cols-2 gap-2 text-[11px] leading-4 text-ink-muted sm:grid-cols-4">
                <span className="truncate rounded-md bg-white/[0.04] px-2.5 py-1.5">DSA {orchestrationSummary.artifacts.dsa}</span>
                <span className="truncate rounded-md bg-white/[0.04] px-2.5 py-1.5">Apt {orchestrationSummary.artifacts.aptitude}</span>
                <span className="truncate rounded-md bg-white/[0.04] px-2.5 py-1.5">Tech {orchestrationSummary.artifacts.technical}</span>
                <span className="truncate rounded-md bg-white/[0.04] px-2.5 py-1.5">HR {orchestrationSummary.artifacts.hr}</span>
              </div>
            )}
          </div>
        )}
        <div
          ref={scrollRef}
          className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-0 py-0 font-mono text-[12px] leading-6 text-ink [scrollbar-color:#4052a8_#090b0f] [scrollbar-width:thin] [&::-webkit-scrollbar]:w-2 [&::-webkit-scrollbar-track]:bg-[#090b0f] [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-accent-blue/70"
        >
          {visibleLogs.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center px-6 text-center">
              <Terminal className="mb-4 h-10 w-10 text-ink-muted" />
              <p className="font-sans text-body-sm text-ink-muted">Logs will appear here when the interview starts.</p>
            </div>
          ) : (
            <div className="min-w-0 px-5 py-4">
              {visibleLogs.map((log) => {
                const agent = cleanGeneratedText(log.agent);
                const message = cleanGeneratedText(log.message);
                return (
                  <div
                    key={log.id}
                    className={cn(
                      "min-w-0 whitespace-pre-wrap break-words py-2 font-mono text-[12px] leading-6",
                      lineTone(log.type)
                    )}
                  >
                    <span className="text-ink-muted">{"> "}</span>
                    <span className="text-ink-muted">{agent}: </span>
                    <span>{message}</span>
                  </div>
                );
              })}
              <div className="h-2" />
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
