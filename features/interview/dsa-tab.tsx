"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Code2,
  Loader2,
  Play,
  Send,
  Timer,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiService } from "@/services/api-service";
import { useWorkflowActions } from "@/hooks/use-workflow-state";
import { useInterviewStore } from "@/stores/interview-store";
import { useSettingsStore } from "@/stores/settings-store";
import Editor from "@monaco-editor/react";
import { codeLanguages, getCodeLanguage } from "@/constants/code-languages";
import { cleanGeneratedText } from "@/lib/generated-text";
import { clearAutosavedValue, readAutosavedValue, writeAutosavedValue } from "@/lib/interview-autosave";
import { cn } from "@/lib/utils";
import type { DSAEvaluationEntry, DSAProblem } from "@/types";
import { InAppConfirmDialog } from "./in-app-confirm-dialog";
import { blockEditorClipboardEvent, installMonacoClipboardGuard } from "./editor-clipboard-guard";

type TestResult = {
  name: string;
  input?: unknown;
  expected?: unknown;
  actual?: unknown;
  stdout?: string;
  stderr?: string;
  compileOutput?: string;
  message?: string;
  time?: string;
  memory?: number;
  status?: string;
  passed: boolean;
};

type EvaluationResponse = {
  id?: string;
  status: "passed" | "failed" | string;
  score: number;
  feedback: string;
  test_results?: TestResult[];
  testResults?: TestResult[];
};

function evaluationTests(response: EvaluationResponse) {
  return response.testResults || response.test_results || [];
}

function formatInlineValue(value: unknown) {
  if (value === undefined || value === null || value === "") return "-";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function formatBlockValue(value: unknown) {
  if (value === undefined || value === null || value === "") return "-";
  if (typeof value === "string") {
    try {
      return JSON.stringify(JSON.parse(value), null, 2);
    } catch {
      return value;
    }
  }
  return JSON.stringify(value, null, 2);
}

function passedCount(tests: TestResult[]) {
  return tests.filter((test) => test.passed).length;
}

function formatTime(value: Date) {
  return value.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

const DSA_ROUND_LIMIT_SECONDS: Record<string, number> = {
  easy: 30 * 60,
  medium: 45 * 60,
  hard: 60 * 60,
};

function formatRoundDuration(seconds: number) {
  const safeSeconds = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(safeSeconds / 60);
  const remainder = safeSeconds % 60;
  return `${minutes}:${remainder.toString().padStart(2, "0")}`;
}

function dsaRoundLimitSeconds(difficulty?: string) {
  return DSA_ROUND_LIMIT_SECONDS[String(difficulty || "").toLowerCase()] || DSA_ROUND_LIMIT_SECONDS.medium;
}

function cleanProblemText(value: unknown, fallback = "") {
  return cleanGeneratedText(value, fallback);
}

function hasRawExecutionDetails(value: unknown) {
  const text = String(value || "");
  return /(?:ReferenceError|SyntaxError|TypeError|RangeError|node:internal|at\s+\S+|[A-Z]:\\)/i.test(text);
}

function simpleTestMessage(test: TestResult) {
  if (test.passed) return "This test passed.";
  const raw = `${test.status || ""}\n${test.message || ""}\n${test.stderr || ""}\n${test.compileOutput || ""}`;
  if (/ReferenceError|is not defined/i.test(raw)) return "Your code uses a name that is not defined.";
  if (/SyntaxError/i.test(raw)) return "Your code has a syntax error.";
  if (/TypeError/i.test(raw)) return "Your code hit a runtime type error.";
  if (/time limit|timed out|timeout/i.test(raw)) return "Your code took too long to finish.";
  if (/compile|compilation/i.test(raw)) return "Your code did not compile.";
  if (test.expected !== undefined && test.actual !== undefined) return "Your answer is wrong for this test case.";
  return "Your answer is wrong. Check the logic and try again.";
}

function safeActualValue(test: TestResult) {
  if (hasRawExecutionDetails(test.actual) || hasRawExecutionDetails(test.stderr) || hasRawExecutionDetails(test.compileOutput)) {
    return "-";
  }
  return formatBlockValue(test.actual);
}

function LanguageDropdown({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const selected = getCodeLanguage(value);

  useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, []);

  return (
    <div ref={containerRef} className="relative w-full md:w-56">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
        className={cn(
          "flex h-10 w-full items-center justify-between rounded-md border border-hairline bg-surface-2 px-3 text-left text-body-sm text-ink transition-colors",
          "hover:border-accent-blue/50 focus-visible:border-accent-blue focus-visible:outline-none",
          disabled && "cursor-not-allowed opacity-60"
        )}
      >
        <span className="truncate">{selected.label}</span>
        <ChevronDown className={cn("h-4 w-4 shrink-0 text-ink-muted transition-transform", open && "rotate-180")} />
      </button>

      {open && !disabled && (
        <div className="absolute right-0 z-50 mt-2 max-h-72 w-full overflow-y-auto rounded-md border border-hairline bg-surface-1 p-1 shadow-xl md:w-56">
          {codeLanguages.map((languageOption) => {
            const active = languageOption.value === selected.value;
            return (
              <button
                key={languageOption.value}
                type="button"
                onClick={() => {
                  onChange(languageOption.value);
                  setOpen(false);
                }}
                className={cn(
                  "flex h-9 w-full items-center justify-between rounded-md px-3 text-left text-body-sm transition-colors",
                  active ? "bg-surface-2 text-ink" : "text-ink-muted hover:bg-surface-2 hover:text-ink"
                )}
              >
                <span className="truncate">{languageOption.label}</span>
                {active && <CheckCircle2 className="h-4 w-4 text-primary" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function DSATab() {
  const {
    interviewId,
    roundRestartKeys,
    dsaProblems,
    dsaSubmissions,
    dsaEvaluationHistory,
    formData,
    addDSASubmission,
    addDSAEvaluationEntry,
    addExecutionLog,
    progressToNextStep,
    setCurrentStep,
    backendWorkflowEnabled,
    workflowState,
  } = useInterviewStore();
  const { advanceWorkflowOrFallback, refreshWorkflowState, isNextStepAllowed } = useWorkflowActions();
  const autoSaveAnswers = useSettingsStore((state) => state.settings.interview.autoSaveAnswers);

  const [selectedProblemId, setSelectedProblemId] = useState("");
  const initialLanguage = getCodeLanguage(formData.language).value;
  const [language, setLanguage] = useState(initialLanguage);
  const [codeByProblem, setCodeByProblem] = useState<Record<string, string>>({});
  const [isRunning, setIsRunning] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [expandedEntryId, setExpandedEntryId] = useState<string | null>(null);
  const [submitConfirmOpen, setSubmitConfirmOpen] = useState(false);
  const [clipboardWarning, setClipboardWarning] = useState("");
  const clipboardWarningTimerRef = useRef<number | null>(null);
  const editorGuardCleanupRef = useRef<(() => void) | null>(null);
  const autoSubmitTriggeredRef = useRef(false);

  const showClipboardWarning = useCallback(() => {
    setClipboardWarning("Copy and paste are not allowed inside the interview editor.");
    if (clipboardWarningTimerRef.current) window.clearTimeout(clipboardWarningTimerRef.current);
    clipboardWarningTimerRef.current = window.setTimeout(() => setClipboardWarning(""), 2500);
  }, []);

  useEffect(
    () => () => {
      if (clipboardWarningTimerRef.current) window.clearTimeout(clipboardWarningTimerRef.current);
      editorGuardCleanupRef.current?.();
    },
    []
  );

  useEffect(() => {
    if (!selectedProblemId && dsaProblems[0]) {
      setSelectedProblemId(dsaProblems[0].id);
    }
  }, [dsaProblems, selectedProblemId]);

  useEffect(() => {
    if (!autoSaveAnswers || !interviewId) return;
    setCodeByProblem((current) => ({
      ...readAutosavedValue<Record<string, string>>(interviewId, "dsa-code", {}),
      ...current,
    }));
  }, [autoSaveAnswers, interviewId]);

  useEffect(() => {
    if (!interviewId) return;
    if (!autoSaveAnswers) {
      clearAutosavedValue(interviewId, "dsa-code");
      return;
    }

    if (Object.keys(codeByProblem).length > 0) {
      writeAutosavedValue(interviewId, "dsa-code", codeByProblem);
    }
  }, [autoSaveAnswers, codeByProblem, interviewId]);

  const selectedProblem = useMemo(
    () => dsaProblems.find((problem) => problem.id === selectedProblemId) || dsaProblems[0],
    [dsaProblems, selectedProblemId]
  );

  const submittedProblemIds = useMemo(
    () => new Set(dsaSubmissions.map((submission) => submission.problemId)),
    [dsaSubmissions]
  );
  const allProblemsSubmitted = dsaProblems.length > 0 && submittedProblemIds.size >= dsaProblems.length;
  const roundDifficulty = formData.difficulty || dsaProblems[0]?.difficulty || "medium";
  const roundLimitSeconds = dsaRoundLimitSeconds(roundDifficulty);
  const [roundStartedAt, setRoundStartedAt] = useState(() => Date.now());
  const [remainingSeconds, setRemainingSeconds] = useState(roundLimitSeconds);
  const [roundTimedOut, setRoundTimedOut] = useState(false);
  const selectedProblemSubmitted = selectedProblem ? submittedProblemIds.has(selectedProblem.id) : false;
  const backendBlocksAptitude =
    backendWorkflowEnabled && Boolean(workflowState) && !isNextStepAllowed("aptitude");

  useEffect(() => {
    const startedAt = Date.now();
    setRoundStartedAt(startedAt);
    setRemainingSeconds(roundLimitSeconds);
    setRoundTimedOut(false);
    autoSubmitTriggeredRef.current = false;
  }, [interviewId, roundRestartKeys.dsa, roundLimitSeconds]);

  useEffect(() => {
    if (!interviewId || dsaProblems.length === 0 || allProblemsSubmitted) return;

    const tick = () => {
      const elapsedSeconds = Math.floor((Date.now() - roundStartedAt) / 1000);
      const nextRemaining = Math.max(0, roundLimitSeconds - elapsedSeconds);
      setRemainingSeconds(nextRemaining);
      if (nextRemaining === 0) setRoundTimedOut(true);
    };

    tick();
    const interval = window.setInterval(tick, 1000);
    return () => window.clearInterval(interval);
  }, [allProblemsSubmitted, dsaProblems.length, interviewId, roundLimitSeconds, roundStartedAt]);

  const submittedCode = selectedProblem
    ? dsaSubmissions.find((submission) => submission.problemId === selectedProblem.id)?.code
    : undefined;
  const codeKey = selectedProblem ? `${selectedProblem.id}:${language}` : "";
  const languageConfig = getCodeLanguage(language);
  const savedCode = codeKey ? codeByProblem[codeKey] : undefined;
  const currentCode =
    savedCode !== undefined
      ? savedCode
      : submittedCode !== undefined
      ? submittedCode
      : languageConfig.starter;

  const elapsedRoundSeconds = useCallback(
    () => Math.min(roundLimitSeconds, Math.max(0, Math.round((Date.now() - roundStartedAt) / 1000))),
    [roundLimitSeconds, roundStartedAt]
  );

  const codeForProblem = useCallback(
    (problem: DSAProblem, submissionLanguage = language) => {
      const submitted = dsaSubmissions.find((submission) => submission.problemId === problem.id);
      const saved = codeByProblem[`${problem.id}:${submissionLanguage}`];
      return saved !== undefined ? saved : submitted?.code ?? getCodeLanguage(submissionLanguage).starter;
    },
    [codeByProblem, dsaSubmissions, language]
  );

  const selectedHistory = useMemo(
    () => dsaEvaluationHistory.filter((entry) => entry.problemId === selectedProblem?.id),
    [dsaEvaluationHistory, selectedProblem?.id]
  );

  const sampleCases = useMemo(() => {
    if (!selectedProblem) return [];
    const examples = (selectedProblem.examples || []).map((example) => ({
      input: example.input,
      output: example.output,
    }));
    const testCaseExamples = (selectedProblem.test_cases || []).map((testCase) => ({
      input: testCase.input,
      output: testCase.expected,
    }));
    return [...examples, ...testCaseExamples].slice(0, 2);
  }, [selectedProblem]);

  useEffect(() => {
    const latest = selectedHistory[selectedHistory.length - 1];
    if (latest) {
      setExpandedEntryId(latest.id);
    }
  }, [selectedHistory]);

  const updateCode = (value: string) => {
    if (!selectedProblem || selectedProblemSubmitted) return;
    setCodeByProblem((current) => ({
      ...current,
      [`${selectedProblem.id}:${language}`]: value,
    }));
  };

  const addEvaluationEntry = useCallback(
    (
      action: "run" | "submit",
      response: EvaluationResponse,
      problem: DSAProblem | undefined = selectedProblem,
      entryLanguage = language
    ) => {
      if (!problem) return null;
      const entry: DSAEvaluationEntry = {
        id: `${action}-${Date.now()}-${Math.random()}`,
        problemId: problem.id,
        action,
        status: response.status,
        score: response.score,
        feedback: response.feedback,
        testResults: evaluationTests(response),
        timestamp: new Date(),
        language: entryLanguage,
      };
      addDSAEvaluationEntry(entry);
      setExpandedEntryId(entry.id);
      return entry;
    },
    [addDSAEvaluationEntry, language, selectedProblem]
  );

  const runSolution = async () => {
    if (!selectedProblem || selectedProblemSubmitted) return;
    setIsRunning(true);

    try {
      const response = await apiService.request<EvaluationResponse>("/api/dsa/run", {
        method: "POST",
        body: {
          problem_id: selectedProblem.id,
          code: currentCode,
          language,
        },
      });
      const entry = addEvaluationEntry("run", response);
      const tests = evaluationTests(response);
      addExecutionLog({
        type: response.status === "passed" ? "success" : "warning",
        agent: "DSA Runner",
        message: `${cleanProblemText(selectedProblem.title)}: ${passedCount(tests)}/${tests.length} test cases passed.`,
      });
      if (entry) {
        setExpandedEntryId(entry.id);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unable to run DSA solution.";
      addEvaluationEntry("run", {
        status: "failed",
        score: 0,
        feedback: message,
        testResults: [],
      });
      addExecutionLog({
        type: "error",
        agent: "DSA Runner",
        message,
      });
    } finally {
      setIsRunning(false);
    }
  };

  const submitProblem = useCallback(
    async (
      problem: DSAProblem,
      code: string,
      submissionLanguage: string,
      options: { source?: "manual" | "timeout"; refreshWorkflow?: boolean } = {}
    ) => {
      if (!interviewId) return null;

      const response = await apiService.request<EvaluationResponse>("/api/dsa/submissions", {
        method: "POST",
        body: {
          interview_id: interviewId,
          problem_id: problem.id,
          code,
          language: submissionLanguage,
          time_taken_seconds: elapsedRoundSeconds(),
        },
      });

      addDSASubmission({
        code,
        language: submissionLanguage,
        problemId: problem.id,
        timestamp: new Date(),
      });
      addEvaluationEntry("submit", response, problem, submissionLanguage);
      const tests = evaluationTests(response);
      addExecutionLog({
        type: response.status === "passed" ? "success" : "warning",
        agent: "DSA Evaluator",
        message:
          options.source === "timeout"
            ? `${cleanProblemText(problem.title)} auto-submitted at the DSA round time limit with ${passedCount(tests)}/${tests.length} test cases passed.`
            : `${cleanProblemText(problem.title)} submitted with ${passedCount(tests)}/${tests.length} test cases passed.`,
      });

      if (options.refreshWorkflow !== false) void refreshWorkflowState();
      return response;
    },
    [addDSASubmission, addEvaluationEntry, addExecutionLog, elapsedRoundSeconds, interviewId, refreshWorkflowState]
  );

  const requestSubmitSolution = () => {
    if (!interviewId || !selectedProblem || selectedProblemSubmitted) return;
    setSubmitConfirmOpen(true);
  };

  const submitSolution = async () => {
    if (!interviewId || !selectedProblem || selectedProblemSubmitted || isSubmitting) return;

    setSubmitConfirmOpen(false);
    setIsSubmitting(true);

    try {
      await submitProblem(selectedProblem, currentCode, language);
      addExecutionLog({
        type: "success",
        agent: "Interview Flow",
        message: "Solution submitted. Review the evaluation, then continue when ready.",
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unable to submit DSA solution.";
      addEvaluationEntry("submit", {
        status: "failed",
        score: 0,
        feedback: message,
        testResults: [],
      });
      addExecutionLog({
        type: "error",
        agent: "DSA Evaluator",
        message,
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  const autoSubmitRemainingProblems = useCallback(async () => {
    if (!interviewId || dsaProblems.length === 0) return;
    const submittedIds = new Set(dsaSubmissions.map((submission) => submission.problemId));
    const pendingProblems = dsaProblems.filter((problem) => !submittedIds.has(problem.id));
    if (pendingProblems.length === 0) return;

    setSubmitConfirmOpen(false);
    setSelectedProblemId(dsaProblems[dsaProblems.length - 1].id);
    setIsSubmitting(true);
    addExecutionLog({
      type: "warning",
      agent: "Interview Flow",
      message: "DSA round time expired. Auto-submitting remaining problems for evaluation.",
    });

    let failedCount = 0;
    try {
      for (const problem of pendingProblems) {
        try {
          await submitProblem(problem, codeForProblem(problem, language), language, {
            source: "timeout",
            refreshWorkflow: false,
          });
        } catch (error) {
          failedCount += 1;
          const message = error instanceof Error ? error.message : "Unable to auto-submit DSA solution.";
          addEvaluationEntry(
            "submit",
            {
              status: "failed",
              score: 0,
              feedback: message,
              testResults: [],
            },
            problem,
            language
          );
          addExecutionLog({
            type: "error",
            agent: "DSA Evaluator",
            message: `${cleanProblemText(problem.title)} could not be auto-submitted: ${message}`,
          });
        }
      }
      void refreshWorkflowState();
      addExecutionLog({
        type: failedCount === 0 ? "success" : "warning",
        agent: "Interview Flow",
        message:
          failedCount === 0
            ? "DSA auto-submit complete. Review the final evaluation, then continue to Aptitude."
            : "DSA auto-submit finished with errors. Review the evaluation panel before continuing.",
      });
    } finally {
      setIsSubmitting(false);
    }
  }, [
    addEvaluationEntry,
    addExecutionLog,
    codeForProblem,
    dsaProblems,
    dsaSubmissions,
    interviewId,
    language,
    refreshWorkflowState,
    submitProblem,
  ]);

  useEffect(() => {
    if (!roundTimedOut || autoSubmitTriggeredRef.current || allProblemsSubmitted) return;
    autoSubmitTriggeredRef.current = true;
    void autoSubmitRemainingProblems();
  }, [allProblemsSubmitted, autoSubmitRemainingProblems, roundTimedOut]);

  const timerIsCritical = remainingSeconds <= 60 && !allProblemsSubmitted;
  const timerLabel = allProblemsSubmitted
    ? "DSA complete"
    : roundTimedOut
    ? "Time expired"
    : `${formatRoundDuration(remainingSeconds)} left`;

  if (!interviewId || dsaProblems.length === 0) {
    return (
      <Card className="bg-surface-1 border-hairline">
        <CardContent className="py-16 text-center">
          <Code2 className="mx-auto mb-4 h-10 w-10 text-ink-muted" />
          <h3 className="mb-2 text-headline text-ink">Start an interview first</h3>
          <p className="mx-auto mb-6 max-w-xl text-body text-ink-muted">
            Submit the form so the backend can generate DSA, aptitude, technical, and HR rounds.
          </p>
          <Button onClick={() => setCurrentStep("form")} className="rounded-pill bg-primary text-on-primary">
            Go to Form
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <>
      <div className="grid h-full min-h-0 grid-cols-1 gap-6 overflow-hidden 2xl:grid-cols-[minmax(0,1fr)_440px]">
      <Card className="flex min-h-0 flex-col overflow-hidden bg-surface-1 border-hairline">
        <CardHeader className="space-y-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div className="min-w-0">
              <CardTitle className="text-headline text-ink">Generated Problems</CardTitle>
              <p className="mt-1 text-body-sm text-ink-muted">
                Choose a problem, run your code as often as needed, then submit once.
              </p>
            </div>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <Badge
                variant="outline"
                className={cn(
                  "w-fit gap-1 border-hairline text-ink-muted",
                  timerIsCritical && "border-gradient-coral text-gradient-coral",
                  allProblemsSubmitted && "border-semantic-success text-semantic-success"
                )}
              >
                <Timer className="h-3.5 w-3.5" />
                {timerLabel}
              </Badge>
              <LanguageDropdown
                value={language}
                onChange={(value) => setLanguage(getCodeLanguage(value).value)}
                disabled={selectedProblemSubmitted || isSubmitting}
              />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
            {dsaProblems.map((problem, index) => {
              const isSelected = problem.id === selectedProblem?.id;
              const isSubmitted = submittedProblemIds.has(problem.id);
              return (
                <button
                  key={problem.id}
                  type="button"
                  onClick={() => setSelectedProblemId(problem.id)}
                  className={cn(
                    "flex min-h-20 flex-col justify-between rounded-md border p-3 text-left transition-colors",
                    isSelected
                      ? "border-accent-blue bg-surface-2 text-ink"
                      : "border-hairline bg-transparent text-ink-muted hover:border-accent-blue/50 hover:text-ink"
                  )}
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="min-w-0 break-words text-caption text-ink-muted">
                      Problem {index + 1}
                      {problem.category ? ` · ${cleanProblemText(problem.category)}` : ""}
                    </span>
                    {isSubmitted && <CheckCircle2 className="h-4 w-4 shrink-0 text-semantic-success" />}
                  </div>
                  <span className="mt-2 line-clamp-2 break-words text-body-sm font-medium">
                    {cleanProblemText(problem.title)}
                  </span>
                </button>
              );
            })}
          </div>
        </CardHeader>

        <CardContent className="min-h-0 flex-1 space-y-6 overflow-y-auto overflow-x-hidden">
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div className="min-w-0">
              <h3 className="break-words text-headline text-ink">
                {cleanProblemText(selectedProblem?.title, "Generated Problem")}
              </h3>
              <div className="mt-2 flex flex-wrap gap-2">
                <Badge variant="outline" className="border-hairline text-ink-muted">
                  {cleanProblemText(selectedProblem?.difficulty)}
                </Badge>
                {selectedProblem?.tags?.slice(0, 4).map((tag) => (
                  <Badge key={tag} variant="outline" className="border-hairline text-ink-muted">
                    {cleanProblemText(tag)}
                  </Badge>
                ))}
                {selectedProblemSubmitted && (
                  <Badge className="bg-semantic-success text-black">Submitted</Badge>
                )}
              </div>
            </div>
          </div>

          <div>
            <h4 className="mb-2 text-body-sm font-medium text-ink">Detailed Problem Statement</h4>
            <p className="whitespace-pre-wrap break-words text-body text-ink-muted">
              {cleanProblemText(selectedProblem?.description)}
            </p>
          </div>

          <div className="rounded-lg border border-hairline bg-surface-2 p-4">
            <h4 className="mb-2 text-body-sm font-medium text-ink">Input and Output Contract</h4>
            <p className="break-words text-body-sm text-ink-muted">
              {languageConfig.contract} The evaluator sends one JSON test case through stdin and compares stdout
              with the expected JSON value.
            </p>
            <p className="mt-2 text-caption text-ink-muted">
              Sample inputs and outputs stay the same for every language because they describe the JSON data, not
              language syntax.
            </p>
          </div>

          {selectedProblem?.constraints && (
            <div>
              <h4 className="mb-2 text-body-sm font-medium text-ink">Constraints</h4>
              <p className="whitespace-pre-wrap break-words text-body-sm text-ink-muted">
                {cleanProblemText(selectedProblem.constraints)}
              </p>
            </div>
          )}

          <div>
            <h4 className="mb-3 text-body-sm font-medium text-ink">Sample Inputs and Outputs</h4>
            <div className="space-y-4">
              {sampleCases.map((sample, index) => (
                <div key={index} className="rounded-lg border border-hairline bg-surface-2">
                  <div className="border-b border-hairline px-4 py-3 text-body-sm font-medium text-ink">
                    Sample {index + 1}
                  </div>
                  <div className="space-y-4 p-4">
                    <div>
                      <p className="mb-2 text-caption uppercase text-ink-muted">Input</p>
                      <pre className="whitespace-pre-wrap break-words rounded-md bg-black/30 p-4 text-caption leading-5 text-ink">
                        {formatBlockValue(sample.input)}
                      </pre>
                    </div>
                    <div>
                      <p className="mb-2 text-caption uppercase text-ink-muted">Expected Output</p>
                      <pre className="whitespace-pre-wrap break-words rounded-md bg-black/30 p-4 text-caption leading-5 text-ink">
                        {formatBlockValue(sample.output)}
                      </pre>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div>
            <h4 className="mb-2 text-body-sm font-medium text-ink">Solution</h4>
            {clipboardWarning && (
              <div className="mb-2 rounded-md border border-gradient-orange/40 bg-gradient-orange/10 px-3 py-2 text-body-sm text-gradient-orange">
                {clipboardWarning}
              </div>
            )}
            <div
              className="overflow-hidden rounded-lg border border-hairline bg-[#0b0f14]"
              onCopy={(event) => blockEditorClipboardEvent(event, showClipboardWarning)}
              onCut={(event) => blockEditorClipboardEvent(event, showClipboardWarning)}
              onPaste={(event) => blockEditorClipboardEvent(event, showClipboardWarning)}
              onDrop={(event) => blockEditorClipboardEvent(event, showClipboardWarning)}
              onContextMenu={(event) => blockEditorClipboardEvent(event, showClipboardWarning)}
            >
              <Editor
                height="360px"
                language={languageConfig.monaco}
                theme="vs-dark"
                value={currentCode}
                onChange={(value) => updateCode(value || "")}
                onMount={(editor) => {
                  editorGuardCleanupRef.current?.();
                  editorGuardCleanupRef.current = installMonacoClipboardGuard(editor, showClipboardWarning);
                }}
                options={{
                  readOnly: selectedProblemSubmitted || isSubmitting,
                  contextmenu: false,
                  minimap: { enabled: false },
                  fontSize: 14,
                  lineHeight: 22,
                  tabSize: languageConfig.tabSize,
                  insertSpaces: true,
                  detectIndentation: false,
                  automaticLayout: true,
                  formatOnPaste: true,
                  formatOnType: true,
                  scrollBeyondLastLine: false,
                  scrollbar: {
                    alwaysConsumeMouseWheel: false,
                    horizontal: "auto",
                    vertical: "auto",
                  },
                  wordWrap: "on",
                  wrappingIndent: "same",
                  lineNumbers: "on",
                  glyphMargin: false,
                  overviewRulerLanes: 0,
                  padding: { top: 12, bottom: 12 },
                }}
              />
            </div>
          </div>

          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <Button
              type="button"
              onClick={runSolution}
              disabled={isRunning || isSubmitting || selectedProblemSubmitted}
              variant="outline"
              className="rounded-md border-hairline"
            >
              {isRunning ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
              {isRunning ? "Running..." : "Run Code"}
            </Button>
            <Button
              onClick={requestSubmitSolution}
              disabled={isRunning || isSubmitting || selectedProblemSubmitted}
              className="rounded-md bg-primary text-on-primary hover:bg-primary/90"
            >
              {isSubmitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Send className="mr-2 h-4 w-4" />}
              {selectedProblemSubmitted ? "Submitted" : isSubmitting ? "Submitting..." : "Submit Final"}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => void advanceWorkflowOrFallback(progressToNextStep)}
               disabled={!allProblemsSubmitted || backendBlocksAptitude}
              className="rounded-md border-hairline sm:ml-auto"
            >
              Continue to Aptitude
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card className="flex min-h-0 flex-col overflow-hidden bg-surface-1 border-hairline">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-headline text-ink">
            <Play className="h-5 w-5 text-accent-blue" />
            Evaluation
          </CardTitle>
        </CardHeader>
        <CardContent className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden">
          {selectedHistory.length === 0 ? (
            <div className="rounded-lg border border-dashed border-hairline p-6 text-center">
              <p className="text-body-sm text-ink-muted">
                Run code to see test results. Final submissions will be locked after one submit.
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {selectedHistory.map((entry, index) => {
                const total = entry.testResults.length;
                const passed = passedCount(entry.testResults);
                const isOpen = expandedEntryId === entry.id;
                const success = total > 0 && passed === total;
                const summaryText =
                  total > 0
                    ? `${passed}/${total} test cases passed, score ${Math.round(entry.score)}/100`
                    : "Run failed before test cases could execute.";

                return (
                  <div key={entry.id} className="min-w-0 overflow-hidden rounded-lg border border-hairline bg-surface-2">
                    <button
                      type="button"
                      onClick={() => setExpandedEntryId(isOpen ? null : entry.id)}
                      className="flex w-full min-w-0 items-start justify-between gap-3 p-3 text-left"
                    >
                      <div className="flex min-w-0 flex-1 gap-3">
                        {success ? (
                          <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-semantic-success" />
                        ) : (
                          <XCircle className="mt-0.5 h-5 w-5 shrink-0 text-gradient-coral" />
                        )}
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <p className="break-words text-body-sm font-medium text-ink">
                              {entry.action === "submit" ? "Solution submitted" : `Run #${index + 1}`}
                            </p>
                            <span className="text-caption text-ink-muted">{formatTime(entry.timestamp)}</span>
                          </div>
                          <p className="mt-1 break-words text-body-sm text-ink-muted">{summaryText}</p>
                        </div>
                      </div>
                      {isOpen ? (
                        <ChevronDown className="mt-1 h-4 w-4 shrink-0 text-ink-muted" />
                      ) : (
                        <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-ink-muted" />
                      )}
                    </button>

                    {isOpen && (
                      <div className="space-y-3 border-t border-hairline p-3">
                        <p className="whitespace-pre-wrap break-words text-body-sm text-ink">
                          {cleanProblemText(entry.feedback)}
                        </p>
                        {entry.testResults.map((test) => (
                          <div
                            key={`${entry.id}-${test.name}`}
                            className="min-w-0 overflow-hidden rounded-md border border-hairline bg-surface-1 p-3"
                          >
                            <div className="mb-2 flex min-w-0 items-start justify-between gap-3">
                              <span className="min-w-0 break-words text-body-sm font-medium text-ink">
                                {cleanProblemText(test.name)}
                              </span>
                              <Badge
                                variant="outline"
                                className={cn(
                                  "shrink-0 border-hairline whitespace-normal text-right",
                                  test.passed ? "text-semantic-success" : "text-gradient-coral"
                                )}
                              >
                                {test.passed ? "Passed" : "Needs work"}
                              </Badge>
                            </div>
                            <div className="space-y-2">
                              <div>
                                <p className="text-micro uppercase text-ink-muted">Input</p>
                                <pre className="mt-1 max-w-full rounded bg-black/20 p-2 text-caption leading-5 text-ink-muted">
                                  {formatBlockValue(test.input)}
                                </pre>
                              </div>
                              <div>
                                <p className="text-micro uppercase text-ink-muted">Expected</p>
                                <pre className="mt-1 max-w-full rounded bg-black/20 p-2 text-caption leading-5 text-ink-muted">
                                  {formatBlockValue(test.expected)}
                                </pre>
                              </div>
                              <div>
                                <p className="text-micro uppercase text-ink-muted">Actual</p>
                                <pre className="mt-1 max-w-full rounded bg-black/20 p-2 text-caption leading-5 text-ink-muted">
                                  {safeActualValue(test)}
                                </pre>
                              </div>
                            </div>
                            <p className="mt-2 whitespace-pre-wrap break-words text-caption text-ink-muted">
                              Result: {simpleTestMessage(test)}
                            </p>
                            {test.time && <p className="break-words text-caption text-ink-muted">Time: {test.time}s</p>}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
      </div>

      <InAppConfirmDialog
        open={submitConfirmOpen}
        title="Submit Final Solution"
        description="Submit this DSA solution as final? You will not be able to resubmit this problem after submission."
        confirmLabel="Submit Final"
        onOpenChange={setSubmitConfirmOpen}
        onConfirm={() => void submitSolution()}
      />
    </>
  );
}
