"use client";

import { useInterviewStore } from "@/stores/interview-store";
import { useWorkflowActions } from "@/hooks/use-workflow-state";
import { VirtualInterviewRound } from "./virtual-interview-round";

export function TechnicalTab() {
  const { technicalQuestions, progressToNextStep, backendWorkflowEnabled, workflowState } = useInterviewStore();
  const { advanceWorkflowOrFallback, isNextStepAllowed } = useWorkflowActions();
  const backendBlocksHR = backendWorkflowEnabled && Boolean(workflowState) && !isNextStepAllowed("hr");

  return (
    <VirtualInterviewRound
      title="Technical Interview"
      description="Start a proctored video call. The bot controls the questions, timers, transcript, and evaluation."
      emptyMessage="Submit the form and complete the earlier rounds before starting technical questions."
      questions={technicalQuestions}
      round="technical"
      agentName="Technical Agent"
      endpoint="/api/technical/answers"
      nextLabel="Continue to HR"
      onComplete={async () => {
        await advanceWorkflowOrFallback(progressToNextStep);
      }}
      completionDisabled={backendBlocksHR}
    />
  );
}
