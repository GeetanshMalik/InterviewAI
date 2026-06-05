import { apiService } from "@/services/api-service";
import type {
  AptitudeQuestion,
  BackendWorkflowStep,
  DSAProblem,
  InterviewQuestion,
  InterviewStep,
  WorkflowEvent,
  WorkflowState,
} from "@/types";

type WorkflowStreamHandlers = {
  onOpen?: () => void;
  onState?: (state: WorkflowState) => void;
  onEvent?: (event: WorkflowEvent) => void;
  onComplete?: () => void;
  onError?: (error: Error) => void;
};

type WorkflowActionPayload = {
  action: string;
  targetStep?: BackendWorkflowStep;
  metadata?: Record<string, unknown>;
};

export type InterviewWorkflowSnapshot = {
  interview: { id: string };
  dsa_problems: DSAProblem[];
  aptitude_questions: AptitudeQuestion[];
  technical_questions: InterviewQuestion[];
  hr_questions: InterviewQuestion[];
};

const workflowEventNames = [
  "workflow_event",
  "workflow_transition",
  "workflow_retry",
  "workflow_error",
  "workflow_cancelled",
  "llm_token",
  "tool_call",
] as const;

function parseEventData<T>(event: MessageEvent) {
  try {
    return JSON.parse(event.data) as T;
  } catch {
    return null;
  }
}

export function isBackendWorkflowEnabled() {
  return process.env.NEXT_PUBLIC_BACKEND_WORKFLOW_ENABLED !== "false";
}

export function workflowStepToInterviewStep(step?: BackendWorkflowStep | string | null): InterviewStep {
  if (step === "aptitude" || step === "technical" || step === "hr" || step === "dsa") {
    return step;
  }
  return step === "completed" ? "hr" : "form";
}

export class WorkflowClient {
  async getWorkflowState(interviewId: string) {
    return apiService.request<WorkflowState>(`/api/interviews/${interviewId}/workflow`);
  }

  async dispatchAction(interviewId: string, payload: WorkflowActionPayload) {
    return apiService.request<WorkflowState>(`/api/interviews/${interviewId}/actions`, {
      method: "POST",
      body: payload,
    });
  }

  async getInterviewSnapshot(interviewId: string) {
    return apiService.request<InterviewWorkflowSnapshot>(`/api/interviews/${interviewId}`);
  }

  subscribeWorkflowStream(
    interviewId: string,
    handlers: WorkflowStreamHandlers,
    options: { follow?: boolean } = {}
  ) {
    if (typeof window === "undefined" || typeof EventSource === "undefined") {
      return () => undefined;
    }

    const params = new URLSearchParams({ follow: String(options.follow ?? true) });
    const token = apiService.getToken();
    if (token) {
      params.set("token", token);
    }

    let source: EventSource | null = null;
    let closed = false;
    let reconnectAttempts = 0;
    let reconnectTimer: number | null = null;

    const connect = () => {
      if (closed) return;
      source = new EventSource(
        `${apiService.baseURL}/api/stream/interviews/${interviewId}/workflow?${params.toString()}`
      );

      source.onopen = () => {
        reconnectAttempts = 0;
        handlers.onOpen?.();
      };

      source.addEventListener("workflow_state", (event) => {
        const state = parseEventData<WorkflowState>(event);
        if (state) handlers.onState?.(state);
      });

      workflowEventNames.forEach((eventName) => {
        source?.addEventListener(eventName, (event) => {
          const workflowEvent = parseEventData<WorkflowEvent>(event);
          if (workflowEvent) handlers.onEvent?.(workflowEvent);
        });
      });

      source.addEventListener("completed", () => {
        handlers.onComplete?.();
        closed = true;
        source?.close();
      });

      source.onerror = () => {
        if (closed) return;
        source?.close();
        reconnectAttempts += 1;
        handlers.onError?.(new Error("Workflow stream disconnected; reconnecting."));
        const delay = Math.min(10000, 1000 * reconnectAttempts);
        reconnectTimer = window.setTimeout(connect, delay);
      };
    };

    connect();

    return () => {
      closed = true;
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      source?.close();
    };
  }

  canDispatch(state: WorkflowState | null | undefined, action: string, targetStep?: BackendWorkflowStep) {
    if (!state) return false;
    return state.allowedActions.some((allowedAction) => {
      if (allowedAction.action !== action) return false;
      return targetStep === undefined || allowedAction.targetStep === targetStep;
    });
  }

  actionForStep(state: WorkflowState | null | undefined, targetStep: InterviewStep) {
    if (!state || targetStep === "form") return null;
    if (workflowStepToInterviewStep(state.currentStep) === targetStep) {
      return { action: "refresh_state", label: "Refresh workflow state" };
    }
    return (
      state.allowedActions.find(
        (allowedAction) =>
          allowedAction.targetStep === targetStep &&
          (allowedAction.action === "move_to_next_step" || allowedAction.action === "move_to_step")
      ) || null
    );
  }
}

export const workflowClient = new WorkflowClient();
