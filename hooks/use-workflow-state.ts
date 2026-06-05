"use client";

import { useCallback, useEffect, useRef } from "react";
import { useInterviewStore } from "@/stores/interview-store";
import { workflowClient, workflowStepToInterviewStep } from "@/services/workflow-client";
import type { BackendWorkflowStep, WorkflowState } from "@/types";

export function useWorkflowState() {
  const interviewId = useInterviewStore((state) => state.interviewId);
  const backendWorkflowEnabled = useInterviewStore((state) => state.backendWorkflowEnabled);
  const setWorkflowState = useInterviewStore((state) => state.setWorkflowState);
  const setWorkflowError = useInterviewStore((state) => state.setWorkflowError);
  const addExecutionLog = useInterviewStore((state) => state.addExecutionLog);
  const streamErrorLoggedRef = useRef(false);
  const workflowEventIdsRef = useRef<Set<string>>(new Set());
  const assetSyncInFlightRef = useRef<Record<string, boolean>>({});

  useEffect(() => {
    if (!backendWorkflowEnabled || !interviewId) return;

    let mounted = true;
    streamErrorLoggedRef.current = false;
    workflowEventIdsRef.current = new Set();

    const syncAssetsWhenReady = async (state: WorkflowState) => {
      if (state.job?.status !== "succeeded") return;
      const current = useInterviewStore.getState();
      if (
        current.interviewId !== state.interviewId ||
        (current.dsaProblems.length > 0 &&
          current.aptitudeQuestions.length > 0 &&
          current.technicalQuestions.length > 0 &&
          current.hrQuestions.length > 0)
      ) {
        return;
      }
      if (assetSyncInFlightRef.current[state.interviewId]) return;
      assetSyncInFlightRef.current[state.interviewId] = true;

      try {
        const snapshot = await workflowClient.getInterviewSnapshot(state.interviewId);
        if (!mounted || useInterviewStore.getState().interviewId !== state.interviewId) return;
        const hasGeneratedAssets =
          snapshot.dsa_problems.length > 0 &&
          snapshot.aptitude_questions.length > 0 &&
          snapshot.technical_questions.length > 0 &&
          snapshot.hr_questions.length > 0;
        if (!hasGeneratedAssets) {
          assetSyncInFlightRef.current[state.interviewId] = false;
          useInterviewStore.getState().setCurrentStep("form");
          setWorkflowError("Interview generation finished without complete round assets. Review the logs and retry.");
          addExecutionLog({
            type: "error",
            agent: "Workflow Orchestrator Agent",
            message: "Interview generation finished without complete round assets. Staying on the form for retry.",
          });
          return;
        }
        useInterviewStore.getState().setInterviewAssets({
          dsaProblems: snapshot.dsa_problems,
          aptitudeQuestions: snapshot.aptitude_questions,
          technicalQuestions: snapshot.technical_questions,
          hrQuestions: snapshot.hr_questions,
        });
        useInterviewStore.getState().setCurrentStep("dsa");
        addExecutionLog({
          type: "success",
          agent: "Interview Orchestrator",
          message: "All interview rounds are ready. Opening the DSA round now.",
        });
      } catch (error) {
        assetSyncInFlightRef.current[state.interviewId] = false;
        setWorkflowError(error instanceof Error ? error.message : "Unable to load generated interview assets.");
      }
    };

    workflowClient
      .getWorkflowState(interviewId)
      .then((state) => {
        if (!mounted) return;
        setWorkflowState(state);
        setWorkflowError(null);
        void syncAssetsWhenReady(state);
      })
      .catch((error) => {
        if (!mounted) return;
        setWorkflowError(error instanceof Error ? error.message : "Unable to load backend workflow state.");
      });

    const closeStream = workflowClient.subscribeWorkflowStream(interviewId, {
      onOpen: () => {
        if (!mounted) return;
        streamErrorLoggedRef.current = false;
        setWorkflowError(null);
      },
      onState: (state) => {
        if (!mounted) return;
        setWorkflowState(state);
        setWorkflowError(null);
        void syncAssetsWhenReady(state);
      },
      onEvent: (event) => {
        if (!mounted) return;
        if (event.id && workflowEventIdsRef.current.has(event.id)) {
          return;
        }
        if (event.id) {
          workflowEventIdsRef.current.add(event.id);
        }
        const eventType =
          event.type === "error" || event.type === "warning" || event.type === "success"
            ? event.type
            : "info";
        addExecutionLog({
          type: eventType,
          agent: event.agent || "Workflow Orchestrator Agent",
          message: event.message || "Workflow event received.",
        });
      },
      onComplete: () => {
        if (!mounted) return;
        void workflowClient
          .getWorkflowState(interviewId)
          .then((state) => {
            setWorkflowState(state);
            void syncAssetsWhenReady(state);
          })
          .catch(() => undefined);
      },
      onError: (error) => {
        if (!mounted) return;
        setWorkflowError(error.message);
        if (streamErrorLoggedRef.current) return;
        streamErrorLoggedRef.current = true;
        addExecutionLog({
          type: "warning",
          agent: "Workflow Stream",
          message: "Backend workflow stream disconnected; polling refresh remains available.",
        });
      },
    });

    const pollFallback = window.setInterval(() => {
      if (!mounted) return;
      const current = useInterviewStore.getState();
      const status = current.workflowState?.job?.status;
      const active = status === "ready" || status === "queued" || status === "running" || status === "retrying";
      if (!active || current.interviewId !== interviewId) return;
      void workflowClient
        .getWorkflowState(interviewId)
        .then((state) => {
          if (!mounted) return;
          setWorkflowState(state);
          setWorkflowError(null);
          void syncAssetsWhenReady(state);
        })
        .catch(() => undefined);
    }, 5000);

    return () => {
      mounted = false;
      window.clearInterval(pollFallback);
      closeStream();
    };
  }, [addExecutionLog, backendWorkflowEnabled, interviewId, setWorkflowError, setWorkflowState]);
}

export function useWorkflowActions() {
  const interviewId = useInterviewStore((state) => state.interviewId);
  const workflowState = useInterviewStore((state) => state.workflowState);
  const backendWorkflowEnabled = useInterviewStore((state) => state.backendWorkflowEnabled);
  const setWorkflowState = useInterviewStore((state) => state.setWorkflowState);
  const setWorkflowError = useInterviewStore((state) => state.setWorkflowError);
  const setCurrentStep = useInterviewStore((state) => state.setCurrentStep);
  const addExecutionLog = useInterviewStore((state) => state.addExecutionLog);

  const applyState = useCallback(
    (state: WorkflowState) => {
      const current = useInterviewStore.getState();
      if (current.interviewId !== state.interviewId) {
        return state;
      }
      setWorkflowState(state);
      setWorkflowError(null);
      setCurrentStep(
        current.dsaProblems.length === 0
          ? "form"
          : workflowStepToInterviewStep(state.currentStep)
      );
      return state;
    },
    [setCurrentStep, setWorkflowError, setWorkflowState]
  );

  const refreshWorkflowState = useCallback(
    async (nextInterviewId = interviewId) => {
      if (!backendWorkflowEnabled || !nextInterviewId) return null;
      try {
        return applyState(await workflowClient.getWorkflowState(nextInterviewId));
      } catch (error) {
        if (useInterviewStore.getState().interviewId !== nextInterviewId) {
          return null;
        }
        const message = error instanceof Error ? error.message : "Unable to refresh backend workflow state.";
        setWorkflowError(message);
        return null;
      }
    },
    [applyState, backendWorkflowEnabled, interviewId, setWorkflowError]
  );

  const dispatchWorkflowAction = useCallback(
    async (
      action: string,
      targetStep?: BackendWorkflowStep,
      metadata: Record<string, unknown> = {}
    ) => {
      if (!backendWorkflowEnabled || !interviewId) return null;
      const actionInterviewId = interviewId;
      try {
        return applyState(
          await workflowClient.dispatchAction(actionInterviewId, {
            action,
            targetStep,
            metadata,
          })
        );
      } catch (error) {
        if (useInterviewStore.getState().interviewId !== actionInterviewId) {
          return null;
        }
        const message = error instanceof Error ? error.message : "Workflow action was not accepted by the backend.";
        setWorkflowError(message);
        addExecutionLog({
          type: "warning",
          agent: "Workflow Orchestrator Agent",
          message,
        });
        return null;
      }
    },
    [addExecutionLog, applyState, backendWorkflowEnabled, interviewId, setWorkflowError]
  );

  const advanceWorkflowOrFallback = useCallback(
    async (fallback?: () => void) => {
      if (backendWorkflowEnabled && workflowState) {
        const targetStep = workflowState.nextAction?.targetStep;
        if (targetStep) {
          setCurrentStep(workflowStepToInterviewStep(targetStep));
        } else {
          fallback?.();
        }
        void dispatchWorkflowAction("move_to_next_step", targetStep, {
          source: "frontend_state_renderer",
        });
        return true;
      }
      fallback?.();
      return true;
    },
    [backendWorkflowEnabled, dispatchWorkflowAction, setCurrentStep, workflowState]
  );

  const moveToWorkflowStep = useCallback(
    async (targetStep: BackendWorkflowStep) => {
      if (!backendWorkflowEnabled || !workflowState) {
        setCurrentStep(workflowStepToInterviewStep(targetStep));
        return true;
      }
      if (workflowStepToInterviewStep(workflowState.currentStep) === workflowStepToInterviewStep(targetStep)) {
        setCurrentStep(workflowStepToInterviewStep(targetStep));
        return true;
      }

      const action = workflowClient.actionForStep(workflowState, workflowStepToInterviewStep(targetStep));
      if (!action) {
        addExecutionLog({
          type: "warning",
          agent: "Workflow Orchestrator Agent",
          message: `Backend workflow has not enabled the ${targetStep} round yet.`,
        });
        return false;
      }

      return Boolean(
        await dispatchWorkflowAction(action.action, action.targetStep, {
          source: "frontend_tab_navigation",
        })
      );
    },
    [addExecutionLog, backendWorkflowEnabled, dispatchWorkflowAction, setCurrentStep, workflowState]
  );

  const isNextStepAllowed = useCallback(
    (targetStep?: BackendWorkflowStep) => {
      if (!backendWorkflowEnabled || !workflowState) return true;
      return (
        workflowClient.canDispatch(workflowState, "move_to_next_step", targetStep) ||
        workflowClient.canDispatch(workflowState, "move_to_step", targetStep)
      );
    },
    [backendWorkflowEnabled, workflowState]
  );

  return {
    refreshWorkflowState,
    dispatchWorkflowAction,
    advanceWorkflowOrFallback,
    moveToWorkflowStep,
    isNextStepAllowed,
  };
}
