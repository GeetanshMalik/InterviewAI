"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { apiService } from "@/services/api-service";
import { useWorkflowActions } from "@/hooks/use-workflow-state";
import { ROUTES } from "@/constants/routes";
import { useInterviewStore } from "@/stores/interview-store";
import { useReportStore } from "@/stores/report-store";
import { useRoadmapStore } from "@/stores/roadmap-store";
import type { Report, Roadmap } from "@/types";
import { cleanGeneratedText } from "@/lib/generated-text";
import { VirtualInterviewRound } from "./virtual-interview-round";

export function HRTab() {
  const { interviewId, hrQuestions, addExecutionLog, backendWorkflowEnabled, workflowState, resetInterview } =
    useInterviewStore();
  const router = useRouter();
  const { addReport } = useReportStore();
  const { addRoadmap } = useRoadmapStore();
  const { refreshWorkflowState, isNextStepAllowed } = useWorkflowActions();
  const [report, setReport] = useState<Report | null>(null);
  const backendBlocksCompletion =
    backendWorkflowEnabled && Boolean(workflowState) && !isNextStepAllowed("completed");

  const startNewInterview = () => {
    resetInterview();
    router.push(ROUTES.INTERVIEW);
  };

  const generateReport = async () => {
    if (!interviewId || report) return;

    try {
      const response = await apiService.request<{ report: Report; roadmap: Roadmap }>("/api/reports/generate", {
        method: "POST",
        body: { interview_id: interviewId },
      });

      addReport(response.report);
      addRoadmap(response.roadmap);
      setReport(response.report);
      void refreshWorkflowState();
      addExecutionLog({
        type: "success",
        agent: "Report Agent",
        message: `Interview report generated with an overall score of ${Math.round(response.report.overallScore)}/100.`,
      });
    } catch (error) {
      addExecutionLog({
        type: "error",
        agent: "Report Agent",
        message: error instanceof Error ? error.message : "Unable to generate report.",
      });
    }
  };

  return (
    <VirtualInterviewRound
      title="HR Round"
      description="Start a proctored HR video call. The HR bot controls the question flow and evaluates spoken confidence fairly."
      emptyMessage="Submit the form and complete the earlier rounds before starting HR questions."
      questions={hrQuestions}
      round="hr"
      agentName="HR Agent"
      endpoint="/api/hr/answers"
      nextLabel={report ? "Report Generated" : "Generate Report"}
      onComplete={generateReport}
      completionDisabled={Boolean(report) || backendBlocksCompletion}
      completionContent={
        report ? (
          <div className="space-y-4">
            <div className="rounded-lg border border-hairline bg-surface-2 p-4">
              <p className="text-caption text-ink-muted">Overall score</p>
              <p className="mt-2 text-display-md text-ink">{Math.round(report.overallScore)}/100</p>
              <p className="mt-2 text-body-sm text-ink-muted">{cleanGeneratedText(report.aiFeedback)}</p>
            </div>
            <div className="flex flex-col gap-2">
              <Button
                type="button"
                onClick={() => router.push(ROUTES.REPORTS)}
                className="rounded-pill bg-primary text-on-primary"
              >
                View Reports
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => router.push(ROUTES.ROADMAPS)}
                className="rounded-pill border-hairline"
              >
                View Roadmap
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={startNewInterview}
                className="rounded-pill border-hairline"
              >
                Start New Interview
              </Button>
            </div>
          </div>
        ) : (
          <p className="text-body-sm text-ink-muted">
            Submit every HR answer, then generate your report and roadmap.
          </p>
        )
      }
    />
  );
}
