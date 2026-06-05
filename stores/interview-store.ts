import { create } from "zustand";
import type {
  InterviewState,
  InterviewStep,
  InterviewFormData,
  DSASubmission,
  AptitudeAnswer,
  TranscriptEntry,
  ExecutionLog,
  DSAProblem,
  AptitudeQuestion,
  InterviewQuestion,
  DSAEvaluationEntry,
  AptitudeRoundResult,
  AnswerRoundResult,
  WorkflowState,
} from "@/types";
import { clearAutosavedValue } from "@/lib/interview-autosave";
import { isBackendWorkflowEnabled, workflowStepToInterviewStep } from "@/services/workflow-client";
import { useSettingsStore } from "@/stores/settings-store";

interface InterviewStore extends InterviewState {
  setCurrentStep: (step: InterviewStep) => void;
  setInterviewSessionStatus: (status: InterviewState["interviewSessionStatus"]) => void;
  resetRound: (step: Exclude<InterviewStep, "form">) => void;
  setBackendWorkflowEnabled: (enabled: boolean) => void;
  setWorkflowState: (workflowState: WorkflowState | null) => void;
  setWorkflowError: (error: string | null) => void;
  updateFormData: (data: Partial<InterviewFormData>) => void;
  setGeneratedInterview: (assets: {
    interviewId: string;
    dsaProblems: DSAProblem[];
    aptitudeQuestions: AptitudeQuestion[];
    technicalQuestions: InterviewQuestion[];
    hrQuestions: InterviewQuestion[];
    workflowState?: WorkflowState | null;
  }) => void;
  setInterviewAssets: (assets: {
    dsaProblems: DSAProblem[];
    aptitudeQuestions: AptitudeQuestion[];
    technicalQuestions: InterviewQuestion[];
    hrQuestions: InterviewQuestion[];
  }) => void;
  addDSASubmission: (submission: DSASubmission) => void;
  addDSAEvaluationEntry: (entry: DSAEvaluationEntry) => void;
  addAptitudeAnswer: (answer: AptitudeAnswer) => void;
  setAptitudeResult: (result: AptitudeRoundResult) => void;
  setAnswerRoundResult: (round: "technical" | "hr", questionId: string, result: AnswerRoundResult) => void;
  clearAnswerRound: (round: "technical" | "hr") => void;
  addTranscriptEntry: (entry: TranscriptEntry, round: "technical" | "hr") => void;
  addExecutionLog: (log: Omit<ExecutionLog, "id" | "timestamp">) => void;
  clearExecutionLogs: () => void;
  setProcessing: (isProcessing: boolean) => void;
  setNavigationLocked: (isNavigationLocked: boolean) => void;
  resetInterview: () => void;
  progressToNextStep: () => void;
}

const initialFormData: InterviewFormData = {
  name: "",
  email: "",
  role: "",
  companyStyle: "faang",
  difficulty: "medium",
  jobDescription: "",
  resume: null,
  skills: [],
  language: "javascript",
};

const stepOrder: InterviewStep[] = ["form", "dsa", "aptitude", "technical", "hr"];
const initialRoundRestartKeys: Record<Exclude<InterviewStep, "form">, number> = {
  dsa: 0,
  aptitude: 0,
  technical: 0,
  hr: 0,
};

function visibleStepForWorkflow(state: InterviewState, workflowState: WorkflowState | null): InterviewStep {
  if (!workflowState) return state.currentStep;
  if (state.interviewId !== workflowState.interviewId) {
    return state.currentStep;
  }
  if (state.dsaProblems.length === 0) {
    return "form";
  }
  return workflowStepToInterviewStep(workflowState.currentStep);
}

function workflowStateSignature(workflowState: WorkflowState | null) {
  if (!workflowState) return "";
  const eventIds = (workflowState.events || []).slice(-5).map((event) => event.id).join(",");
  const artifactCounts = workflowState.orchestration?.artifactCounts;
  return [
    workflowState.interviewId,
    workflowState.currentStep,
    workflowState.status,
    workflowState.job?.status,
    workflowState.job?.currentNode,
    workflowState.job?.attempt,
    workflowState.job?.workerId,
    workflowState.job?.queuePosition,
    workflowState.job?.queueDepth,
    workflowState.job?.leaseExpiresAt,
    workflowState.job?.lastHeartbeatAt,
    workflowState.job?.updatedAt,
    workflowState.job?.elapsedSeconds,
    workflowState.job?.heartbeatAgeSeconds,
    workflowState.job?.isStale,
    workflowState.job?.staleReason,
    workflowState.job?.error,
    artifactCounts?.dsa,
    artifactCounts?.aptitude,
    artifactCounts?.technical,
    artifactCounts?.hr,
    workflowState.orchestration?.toolDecisionCount,
    workflowState.orchestration?.planningCritiqueCount,
    eventIds,
  ].join("|");
}

export const useInterviewStore = create<InterviewStore>((set, get) => ({
  currentStep: "form",
  interviewSessionStatus: "idle",
  roundRestartKeys: initialRoundRestartKeys,
  backendWorkflowEnabled: isBackendWorkflowEnabled(),
  workflowState: null,
  workflowError: null,
  formData: initialFormData,
  dsaSubmissions: [],
  dsaEvaluationHistory: [],
  aptitudeAnswers: [],
  aptitudeResult: null,
  technicalResults: {},
  hrResults: {},
  technicalTranscript: [],
  hrTranscript: [],
  isProcessing: false,
  isNavigationLocked: false,
  executionLogs: [],
  interviewId: null,
  dsaProblems: [],
  aptitudeQuestions: [],
  technicalQuestions: [],
  hrQuestions: [],

  setCurrentStep: (step) => set({ currentStep: step }),

  setInterviewSessionStatus: (interviewSessionStatus) =>
    set({
      interviewSessionStatus,
      isNavigationLocked: interviewSessionStatus === "active",
    }),

  resetRound: (step) =>
    set((state) => {
      const nextKeys = {
        ...state.roundRestartKeys,
        [step]: state.roundRestartKeys[step] + 1,
      };
      if (state.interviewId) {
        if (step === "dsa") {
          clearAutosavedValue(state.interviewId, "dsa-code");
        } else if (step === "aptitude") {
          clearAutosavedValue(state.interviewId, "aptitude-answers");
        } else {
          clearAutosavedValue(state.interviewId, `${step}-spoken-answers`);
          clearAutosavedValue(state.interviewId, `${step}-code-answers`);
        }
      }
      if (step === "dsa") {
        return { dsaSubmissions: [], dsaEvaluationHistory: [], roundRestartKeys: nextKeys };
      }
      if (step === "aptitude") {
        return { aptitudeAnswers: [], aptitudeResult: null, roundRestartKeys: nextKeys };
      }
      if (step === "technical") {
        return { technicalResults: {}, technicalTranscript: [], roundRestartKeys: nextKeys };
      }
      return { hrResults: {}, hrTranscript: [], roundRestartKeys: nextKeys };
    }),

  setBackendWorkflowEnabled: (enabled) => set({ backendWorkflowEnabled: enabled }),

  setWorkflowState: (workflowState) =>
    set((state) => {
      if (workflowState && state.interviewId !== workflowState.interviewId) {
        return state;
      }
      const currentStep = visibleStepForWorkflow(state, workflowState);
      if (
        workflowStateSignature(state.workflowState) === workflowStateSignature(workflowState) &&
        state.currentStep === currentStep &&
        (!workflowState || state.workflowError === null)
      ) {
        return state;
      }
      return {
        workflowState,
        workflowError: workflowState ? null : state.workflowError,
        currentStep,
      };
    }),

  setWorkflowError: (error) => set({ workflowError: error }),

  updateFormData: (data) =>
    set((state) => ({
      formData: { ...state.formData, ...data },
    })),

  setGeneratedInterview: (assets) =>
    set((state) => ({
      interviewId: assets.interviewId,
      dsaProblems: assets.dsaProblems,
      aptitudeQuestions: assets.aptitudeQuestions,
      technicalQuestions: assets.technicalQuestions,
      hrQuestions: assets.hrQuestions,
      workflowState: assets.workflowState ?? null,
      workflowError: null,
      currentStep:
        assets.workflowState && assets.dsaProblems.length > 0
          ? workflowStepToInterviewStep(assets.workflowState.currentStep)
          : "form",
      roundRestartKeys: initialRoundRestartKeys,
      dsaSubmissions: [],
      dsaEvaluationHistory: [],
      aptitudeAnswers: [],
      aptitudeResult: null,
      technicalResults: {},
      hrResults: {},
      technicalTranscript: [],
      hrTranscript: [],
      interviewSessionStatus: "active",
      isNavigationLocked: true,
    })),

  setInterviewAssets: (assets) =>
    set({
      dsaProblems: assets.dsaProblems,
      aptitudeQuestions: assets.aptitudeQuestions,
      technicalQuestions: assets.technicalQuestions,
      hrQuestions: assets.hrQuestions,
    }),

  addDSASubmission: (submission) =>
    set((state) => ({
      dsaSubmissions: [...state.dsaSubmissions, submission],
    })),

  addDSAEvaluationEntry: (entry) =>
    set((state) => ({
      dsaEvaluationHistory: [...state.dsaEvaluationHistory, entry],
    })),

  addAptitudeAnswer: (answer) =>
    set((state) => ({
      aptitudeAnswers: [...state.aptitudeAnswers, answer],
    })),

  setAptitudeResult: (result) => set({ aptitudeResult: result }),

  setAnswerRoundResult: (round, questionId, result) =>
    set((state) => ({
      [round === "technical" ? "technicalResults" : "hrResults"]: {
        ...state[round === "technical" ? "technicalResults" : "hrResults"],
        [questionId]: result,
      },
    })),

  clearAnswerRound: (round) =>
    set({
      [round === "technical" ? "technicalResults" : "hrResults"]: {},
      [round === "technical" ? "technicalTranscript" : "hrTranscript"]: [],
    }),

  addTranscriptEntry: (entry, round) =>
    set((state) => ({
      [round === "technical" ? "technicalTranscript" : "hrTranscript"]: [
        ...state[round === "technical" ? "technicalTranscript" : "hrTranscript"],
        entry,
      ],
    })),

  addExecutionLog: (log) =>
    set((state) => {
      if (!useSettingsStore.getState().settings.interview.showExecutionLogs) {
        return state;
      }

      return {
        executionLogs: [
          ...state.executionLogs,
          {
            ...log,
            id: `log-${Date.now()}-${Math.random()}`,
            timestamp: new Date(),
          },
        ].slice(-500),
      };
    }),

  clearExecutionLogs: () => set({ executionLogs: [] }),

  setProcessing: (isProcessing) => set({ isProcessing }),

  setNavigationLocked: (isNavigationLocked) => set({ isNavigationLocked }),

  progressToNextStep: () => {
    const currentStep = get().currentStep;
    const currentIndex = stepOrder.indexOf(currentStep);
    if (currentIndex < stepOrder.length - 1) {
      set({ currentStep: stepOrder[currentIndex + 1] });
    }
  },

  resetInterview: () =>
    set({
      currentStep: "form",
      interviewSessionStatus: "idle",
      roundRestartKeys: initialRoundRestartKeys,
      workflowState: null,
      workflowError: null,
      formData: initialFormData,
      dsaSubmissions: [],
      dsaEvaluationHistory: [],
      aptitudeAnswers: [],
      aptitudeResult: null,
      technicalResults: {},
      hrResults: {},
      technicalTranscript: [],
      hrTranscript: [],
      isProcessing: false,
      isNavigationLocked: false,
      executionLogs: [],
      interviewId: null,
      dsaProblems: [],
      aptitudeQuestions: [],
      technicalQuestions: [],
      hrQuestions: [],
    }),
}));
