"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { useInterviewStore } from "@/stores/interview-store";
import { useWorkflowActions, useWorkflowState } from "@/hooks/use-workflow-state";
import { workflowClient, workflowStepToInterviewStep } from "@/services/workflow-client";
import { AlertTriangle, Brain, Code, FileText, Maximize2, MessageSquare, RotateCcw, ShieldAlert, Video } from "lucide-react";
import { cn } from "@/lib/utils";
import type { InterviewStep } from "@/types";

interface InterviewTabsProps {
  children: {
    form: React.ReactNode;
    dsa: React.ReactNode;
    aptitude: React.ReactNode;
    technical: React.ReactNode;
    hr: React.ReactNode;
  };
}

const tabs = [
  { value: "form", label: "Form", icon: FileText },
  { value: "dsa", label: "DSA", icon: Code },
  { value: "aptitude", label: "Aptitude", icon: Brain },
  { value: "technical", label: "Technical", icon: Video },
  { value: "hr", label: "HR Round", icon: MessageSquare },
] as const;

type RoundStep = Exclude<InterviewStep, "form">;
type FullscreenBlock = {
  mode: "recover" | "restart";
  round: RoundStep;
  message: string;
} | null;

const roundOrder: RoundStep[] = ["dsa", "aptitude", "technical", "hr"];

function isRoundStep(step: InterviewStep): step is RoundStep {
  return step === "dsa" || step === "aptitude" || step === "technical" || step === "hr";
}

function roundLabel(step: RoundStep) {
  if (step === "dsa") return "DSA";
  if (step === "hr") return "HR";
  return step[0].toUpperCase() + step.slice(1);
}

export function InterviewTabs({ children }: InterviewTabsProps) {
  useWorkflowState();

  const {
    currentStep,
    interviewSessionStatus,
    setCurrentStep,
    setInterviewSessionStatus,
    resetRound,
    setNavigationLocked,
    roundRestartKeys,
    addExecutionLog,
    interviewId,
    backendWorkflowEnabled,
    workflowState,
    dsaProblems,
    dsaSubmissions,
    aptitudeQuestions,
    aptitudeAnswers,
    technicalQuestions,
    technicalResults,
    hrQuestions,
    hrResults,
  } = useInterviewStore();
  const { dispatchWorkflowAction, moveToWorkflowStep } = useWorkflowActions();
  const [fullscreenBlock, setFullscreenBlock] = useState<FullscreenBlock>(null);
  const exitCountRef = useRef(0);
  const activeRoundRef = useRef<RoundStep | null>(null);
  const fullscreenBlockRef = useRef<FullscreenBlock>(null);
  const completingFullscreenRef = useRef(false);
  const lastIntegrityViolationAtRef = useRef(0);

  const submittedDsaIds = new Set(dsaSubmissions.map((submission) => submission.problemId));
  const submittedAptitudeIds = new Set(aptitudeAnswers.map((answer) => answer.questionId));
  const formComplete = Boolean(interviewId && dsaProblems.length > 0);
  const dsaComplete = dsaProblems.length > 0 && submittedDsaIds.size >= dsaProblems.length;
  const aptitudeComplete =
    aptitudeQuestions.length > 0 && submittedAptitudeIds.size >= aptitudeQuestions.length;
  const technicalComplete =
    technicalQuestions.length > 0 && Object.keys(technicalResults).length >= technicalQuestions.length;
  const hrComplete = hrQuestions.length > 0 && Object.keys(hrResults).length >= hrQuestions.length;
  const backendControlsFlow = backendWorkflowEnabled && Boolean(interviewId && workflowState);
  const generationMissingAssets = backendControlsFlow && dsaProblems.length === 0;
  const generationPending =
    generationMissingAssets &&
    ["ready", "queued", "running", "retrying"].includes(String(workflowState?.job?.status || ""));
  const generationFailed =
    generationMissingAssets && ["failed", "cancelled"].includes(String(workflowState?.job?.status || ""));
  const displayedStep = generationMissingAssets
    ? "form"
    : backendControlsFlow
    ? workflowStepToInterviewStep(workflowState?.currentStep)
    : currentStep;
  const activeRound = isRoundStep(displayedStep) && formComplete ? displayedStep : null;
  const hrRoundComplete = hrQuestions.length > 0 && Object.keys(hrResults).length >= hrQuestions.length;
  const workflowComplete = workflowState?.currentStep === "completed";
  const fullscreenSessionComplete = workflowComplete || (displayedStep === "hr" && hrRoundComplete);

  const isRoundComplete = useCallback(
    (step: RoundStep) => {
      const backendComplete = Boolean(workflowState?.roundProgress?.[step]?.isComplete);
      if (step === "dsa") return backendComplete || dsaComplete;
      if (step === "aptitude") return backendComplete || aptitudeComplete;
      if (step === "technical") return backendComplete || technicalComplete;
      return backendComplete || hrComplete;
    },
    [aptitudeComplete, dsaComplete, hrComplete, technicalComplete, workflowState?.roundProgress]
  );

  const fullscreenGuardRound = useMemo(() => {
    if (!activeRound || !formComplete || fullscreenSessionComplete) return null;
    const startIndex = Math.max(0, roundOrder.indexOf(activeRound));
    return roundOrder.slice(startIndex).find((step) => !isRoundComplete(step)) || null;
  }, [activeRound, formComplete, fullscreenSessionComplete, isRoundComplete]);
  const shouldLockSidebar = interviewSessionStatus === "active" && fullscreenBlock?.mode !== "restart";

  useEffect(() => {
    exitCountRef.current = 0;
    lastIntegrityViolationAtRef.current = 0;
    setFullscreenBlock(null);
  }, [interviewId]);

  useEffect(() => {
    fullscreenBlockRef.current = fullscreenBlock;
  }, [fullscreenBlock]);

  useEffect(() => {
    setNavigationLocked(shouldLockSidebar);
    return () => setNavigationLocked(false);
  }, [setNavigationLocked, shouldLockSidebar]);

  useEffect(() => {
    activeRoundRef.current = fullscreenGuardRound;
  }, [fullscreenGuardRound]);

  const requestAppFullscreen = useCallback(async () => {
    if (typeof document === "undefined") return false;
    if (document.fullscreenElement) {
      setFullscreenBlock(null);
      return true;
    }
    const target = document.documentElement;
    if (!target.requestFullscreen) {
      setFullscreenBlock(null);
      return true;
    }
    try {
      await target.requestFullscreen();
      setFullscreenBlock(null);
      addExecutionLog({
        type: "success",
        agent: "AI Proctor",
        message: "Fullscreen mode restored. Continue the interview.",
      });
      return true;
    } catch {
      const round = activeRoundRef.current || fullscreenGuardRound || activeRound || "dsa";
      setFullscreenBlock({
        mode: "recover",
        round,
        message: "Fullscreen permission was not granted. Re-enter fullscreen to continue the interview.",
      });
      return false;
    }
  }, [activeRound, addExecutionLog, fullscreenGuardRound]);

  const restartBlockedRound = useCallback(async () => {
    const block = fullscreenBlock;
    if (!block) return;
    const restored = await requestAppFullscreen();
    if (!restored) return;
    setInterviewSessionStatus("active");
    setNavigationLocked(true);
    setCurrentStep(block.round);
    setFullscreenBlock(null);
    addExecutionLog({
      type: "warning",
      agent: "AI Proctor",
      message: `${roundLabel(block.round)} round restarted after fullscreen integrity lock.`,
    });
  }, [
    addExecutionLog,
    fullscreenBlock,
    requestAppFullscreen,
    setCurrentStep,
    setInterviewSessionStatus,
    setNavigationLocked,
  ]);

  const registerIntegrityViolation = useCallback(
    (message: string, source: "fullscreen" | "visibility" | "focus" | "keyboard") => {
      if (completingFullscreenRef.current) return;
      if (fullscreenBlockRef.current?.mode === "restart") return;
      const round = activeRoundRef.current;
      if (!round) return;
      if (isRoundComplete(round)) {
        setFullscreenBlock(null);
        return;
      }

      const now = Date.now();
      if (now - lastIntegrityViolationAtRef.current < 1500) return;
      lastIntegrityViolationAtRef.current = now;

      const nextExitCount = exitCountRef.current + 1;
      exitCountRef.current = nextExitCount;
      if (nextExitCount === 1) {
        setFullscreenBlock({ mode: "recover", round, message });
        addExecutionLog({ type: "warning", agent: "AI Proctor", message });
        return;
      }

      const stoppedMessage =
        source === "fullscreen"
          ? `Fullscreen was exited again. ${roundLabel(round)} round has been stopped; start this round again to continue.`
          : `Interview focus changed again. ${roundLabel(round)} round has been stopped; start this round again to continue.`;
      resetRound(round);
      setCurrentStep(round);
      void dispatchWorkflowAction("restart_round", round, {
        source: "fullscreen_guard",
        violationSource: source,
        fullscreenExitCount: nextExitCount,
      });
      setInterviewSessionStatus("stopped");
      setNavigationLocked(false);
      setFullscreenBlock({ mode: "restart", round, message: stoppedMessage });
      addExecutionLog({ type: "error", agent: "AI Proctor", message: stoppedMessage });
    },
    [
      addExecutionLog,
      dispatchWorkflowAction,
      isRoundComplete,
      resetRound,
      setCurrentStep,
      setInterviewSessionStatus,
      setNavigationLocked,
    ]
  );

  useEffect(() => {
    if (typeof document === "undefined") return;
    const handleFullscreenChange = () => {
      if (document.fullscreenElement) {
        if (fullscreenBlock?.mode === "recover") setFullscreenBlock(null);
        return;
      }
      registerIntegrityViolation(
        "Fullscreen was exited. Re-enter fullscreen to continue the interview.",
        "fullscreen"
      );
    };

    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", handleFullscreenChange);
  }, [fullscreenBlock?.mode, registerIntegrityViolation]);

  useEffect(() => {
    if (typeof document === "undefined") return;
    const appSwitchMessage =
      "Interview window lost focus or another app was opened. Re-enter fullscreen to continue the interview.";

    const handleVisibilityChange = () => {
      if (document.visibilityState === "hidden") {
        registerIntegrityViolation(appSwitchMessage, "visibility");
      }
    };
    const handleWindowBlur = () => {
      registerIntegrityViolation(appSwitchMessage, "focus");
    };
    const handlePageHide = () => {
      registerIntegrityViolation(appSwitchMessage, "visibility");
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      const key = event.key.toLowerCase();
      if (key === "meta" || key === "os" || event.metaKey || (event.altKey && key === "tab")) {
        event.preventDefault();
        registerIntegrityViolation(appSwitchMessage, "keyboard");
      }
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("blur", handleWindowBlur);
    window.addEventListener("pagehide", handlePageHide);
    window.addEventListener("keydown", handleKeyDown, true);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("blur", handleWindowBlur);
      window.removeEventListener("pagehide", handlePageHide);
      window.removeEventListener("keydown", handleKeyDown, true);
    };
  }, [registerIntegrityViolation]);

  useEffect(() => {
    if (!fullscreenGuardRound || typeof document === "undefined") return;
    if (!document.fullscreenElement && !fullscreenBlock) {
      setFullscreenBlock({
        mode: "recover",
        round: fullscreenGuardRound,
        message: "Re-enter fullscreen to continue the interview.",
      });
    }
  }, [fullscreenBlock, fullscreenGuardRound]);

  useEffect(() => {
    if (!fullscreenSessionComplete || typeof document === "undefined") return;
    setInterviewSessionStatus("completed");
    setNavigationLocked(false);
    setFullscreenBlock(null);
    activeRoundRef.current = null;
    if (!document.fullscreenElement) return;
    completingFullscreenRef.current = true;
    document
      .exitFullscreen()
      .catch(() => undefined)
      .finally(() => {
        window.setTimeout(() => {
          completingFullscreenRef.current = false;
        }, 250);
      });
  }, [fullscreenSessionComplete, setInterviewSessionStatus, setNavigationLocked]);

  const canOpen = (step: InterviewStep) => {
    if (generationMissingAssets) {
      return step === "form";
    }
    if (backendControlsFlow) {
      if (workflowStepToInterviewStep(workflowState?.currentStep) === step) return true;
      return Boolean(workflowClient.actionForStep(workflowState, step));
    }
    if (step === "form") return true;
    if (step === "dsa") return formComplete;
    if (step === "aptitude") return dsaComplete;
    if (step === "technical") return aptitudeComplete;
    if (step === "hr") return technicalComplete;
    return false;
  };

  const isStepComplete = (step: InterviewStep) => {
    if (backendControlsFlow && step !== "form") {
      return Boolean(workflowState?.roundProgress?.[step]?.isComplete);
    }
    if (step === "form") return formComplete;
    if (step === "dsa") return dsaComplete;
    if (step === "aptitude") return aptitudeComplete;
    if (step === "technical") return technicalComplete;
    if (step === "hr") return hrComplete;
    return false;
  };

  const lockedMessage = (step: InterviewStep) => {
    if (generationFailed) {
      return `Interview generation did not finish. Review the execution logs and start again from the form.`;
    }
    if (generationPending) {
      return `Autonomous agents are still preparing the generated rounds. ${step} will unlock as soon as assets are ready.`;
    }
    if (backendControlsFlow) {
      return `Backend workflow has not enabled the ${step} round yet.`;
    }
    if (step === "dsa") return "Start the interview form before opening DSA.";
    if (step === "aptitude") return "Submit all DSA problems before opening Aptitude.";
    if (step === "technical") return "Submit the Aptitude round before opening Technical.";
    if (step === "hr") return "Submit all Technical answers before opening HR.";
    return "Complete the previous round first.";
  };

  return (
    <div className="relative flex min-h-0 flex-1 flex-col gap-4 overflow-hidden">
      {/* Horizontal Navbar */}
      <div className="flex shrink-0 items-center gap-1 overflow-x-auto rounded-lg border border-hairline bg-surface-1 p-1">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const isActive = displayedStep === tab.value;
          const isCompleted = isStepComplete(tab.value);
          const isLocked = !canOpen(tab.value);
          
          return (
            <button
              key={tab.value}
              onClick={() => {
                if (isLocked) {
                  addExecutionLog({
                    type: "warning",
                    agent: "Interview Flow",
                    message: lockedMessage(tab.value),
                  });
                  return;
                }
                if (backendControlsFlow && tab.value !== "form") {
                  void moveToWorkflowStep(tab.value);
                  return;
                }
                setCurrentStep(tab.value);
              }}
              disabled={isLocked}
              className={cn(
                "flex items-center gap-2 px-4 py-2.5 rounded-md transition-all whitespace-nowrap",
                "text-body-sm font-medium",
                isActive
                  ? "bg-surface-2 text-ink"
                  : isCompleted
                  ? "text-semantic-success hover:bg-surface-2/50"
                  : isLocked
                  ? "cursor-not-allowed text-ink-muted/40"
                  : "text-ink-muted hover:bg-surface-2/50 hover:text-ink"
              )}
            >
              <Icon className="w-4 h-4 flex-shrink-0" />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>

      {/* Content */}
      <div className="min-h-0 flex-1 overflow-hidden">
        {displayedStep === "form" && children.form}
        {displayedStep === "dsa" && <div key={`dsa-${roundRestartKeys.dsa}`} className="h-full min-h-0">{children.dsa}</div>}
        {displayedStep === "aptitude" && (
          <div key={`aptitude-${roundRestartKeys.aptitude}`} className="h-full min-h-0">{children.aptitude}</div>
        )}
        {displayedStep === "technical" && (
          <div key={`technical-${roundRestartKeys.technical}`} className="h-full min-h-0">{children.technical}</div>
        )}
        {displayedStep === "hr" && <div key={`hr-${roundRestartKeys.hr}`} className="h-full min-h-0">{children.hr}</div>}
      </div>

      {fullscreenBlock && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/85 p-4 backdrop-blur-md">
          <div className="w-[min(560px,calc(100vw-2rem))] rounded-lg border border-accent-blue/60 bg-surface-1 p-6 text-center shadow-2xl">
            {fullscreenBlock.mode === "recover" ? (
              <ShieldAlert className="mx-auto mb-4 h-10 w-10 text-accent-blue" />
            ) : (
              <AlertTriangle className="mx-auto mb-4 h-10 w-10 text-gradient-coral" />
            )}
            <h3 className="text-headline text-ink">
              {fullscreenBlock.mode === "recover" ? "Return to Fullscreen" : "Round Stopped"}
            </h3>
            <p className="mx-auto mt-3 max-w-lg break-words text-body-sm text-ink-muted">
              {fullscreenBlock.message}
            </p>
            <div className="mt-6 flex flex-col justify-center gap-3 sm:flex-row">
              {fullscreenBlock.mode === "recover" ? (
                <Button type="button" onClick={() => void requestAppFullscreen()} className="rounded-md bg-primary text-on-primary">
                  <Maximize2 className="mr-2 h-4 w-4" />
                  Re-enter Fullscreen
                </Button>
              ) : (
                <Button type="button" onClick={() => void restartBlockedRound()} className="rounded-md bg-primary text-on-primary">
                  <RotateCcw className="mr-2 h-4 w-4" />
                  Start {roundLabel(fullscreenBlock.round)} Again
                </Button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
