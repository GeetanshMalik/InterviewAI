"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Brain, CheckCircle2, Circle, Send, Timer } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiService } from "@/services/api-service";
import { retryRequest } from "@/services/retry-request";
import { useWorkflowActions } from "@/hooks/use-workflow-state";
import { useInterviewStore } from "@/stores/interview-store";
import { useSettingsStore } from "@/stores/settings-store";
import type { AptitudeQuestion, AptitudeRoundResult } from "@/types";
import { cleanGeneratedText } from "@/lib/generated-text";
import { clearAutosavedValue, readAutosavedValue, writeAutosavedValue } from "@/lib/interview-autosave";
import { cn } from "@/lib/utils";
import { InAppConfirmDialog } from "./in-app-confirm-dialog";

function questionText(question: AptitudeQuestion) {
  return cleanGeneratedText(question.question_text || question.question, "Question");
}

function optionEntries(options: AptitudeQuestion["options"]) {
  if (Array.isArray(options)) {
    return options.map((value, index) => [String.fromCharCode(65 + index), cleanGeneratedText(value)] as const);
  }
  return Object.entries(options || {}).map(([key, value]) => [key, cleanGeneratedText(value)] as const);
}

function optionValueForKey(question: AptitudeQuestion, key?: string) {
  if (!key) return "";
  return optionEntries(question.options).find(([optionKey]) => optionKey === key)?.[1] || "";
}

function comparableNumber(value?: unknown) {
  const text = String(value || "").trim().toLowerCase().replace(/,/g, "");
  if (!text) return null;
  const fraction = text.match(/^([-+]?\d+(?:\.\d+)?)\s*\/\s*([-+]?\d+(?:\.\d+)?)$/);
  if (fraction) {
    const numerator = Number(fraction[1]);
    const denominator = Number(fraction[2]);
    if (Number.isFinite(numerator) && Number.isFinite(denominator) && denominator !== 0) {
      return numerator / denominator;
    }
  }
  const percent = text.match(/^([-+]?\d+(?:\.\d+)?)\s*(?:%|percent)$/);
  if (percent) {
    const number = Number(percent[1]);
    return Number.isFinite(number) ? number / 100 : null;
  }
  const number = Number(text);
  return Number.isFinite(number) ? number : null;
}

function comparableSequence(value?: unknown) {
  const text = String(value || "").trim();
  if (!text.includes(",") || text.includes("/")) return null;
  const matches = text.replace(/(?<=\d),(?=\d{3}\b)/g, "").match(/[-+]?\d+(?:\.\d+)?/g);
  return matches && matches.length >= 2 ? matches.map((item) => Number(item)) : null;
}

function answerValuesMatch(left?: unknown, right?: unknown) {
  const leftText = String(left || "").trim().toLowerCase();
  const rightText = String(right || "").trim().toLowerCase();
  if (!leftText || !rightText) return false;
  const leftSequence = comparableSequence(leftText);
  const rightSequence = comparableSequence(rightText);
  if (leftSequence || rightSequence) {
    return Boolean(
      leftSequence &&
        rightSequence &&
        leftSequence.length === rightSequence.length &&
        leftSequence.every((value, index) => value === rightSequence[index])
    );
  }
  const leftNumber = comparableNumber(leftText);
  const rightNumber = comparableNumber(rightText);
  if (leftNumber !== null && rightNumber !== null) {
    return Math.abs(leftNumber - rightNumber) < 1e-9;
  }
  return leftText === rightText;
}

type AptitudeEvaluation = AptitudeRoundResult["per_question_results"][number];

function acceptedOptionsFor(evaluation?: AptitudeEvaluation) {
  return new Set(
    [
      evaluation?.correct,
      ...(evaluation?.correct_options || []),
      ...(evaluation?.accepted_options || []),
    ].filter(Boolean)
  );
}

function acceptedValuesFor(evaluation?: AptitudeEvaluation) {
  return [
    evaluation?.correct_value,
    ...(evaluation?.correct_values || []),
    ...(evaluation?.accepted_values || []),
  ].filter((value) => value !== undefined && value !== null && String(value).trim() !== "");
}

function seededNumber(seed: string) {
  let value = 2166136261;
  for (let index = 0; index < seed.length; index += 1) {
    value ^= seed.charCodeAt(index);
    value = Math.imul(value, 16777619);
  }
  return value >>> 0;
}

function seededShuffle<T>(items: T[], seed: string) {
  const shuffled = [...items];
  let state = seededNumber(seed) || 1;
  const next = () => {
    state = Math.imul(state ^ (state >>> 15), 1 | state);
    state ^= state + Math.imul(state ^ (state >>> 7), 61 | state);
    return ((state ^ (state >>> 14)) >>> 0) / 4294967296;
  };
  for (let index = shuffled.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(next() * (index + 1));
    [shuffled[index], shuffled[swapIndex]] = [shuffled[swapIndex], shuffled[index]];
  }
  return shuffled;
}

function displayOptionEntries(question: AptitudeQuestion, seed: string) {
  return seededShuffle(optionEntries(question.options), `${seed}:${question.id}:options`).map(
    ([originalKey, value], index) => ({
      displayKey: String.fromCharCode(65 + index),
      originalKey,
      value,
    })
  );
}

const APTITUDE_ROUND_LIMIT_SECONDS = 5 * 60;

function formatRoundDuration(seconds: number) {
  const safeSeconds = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(safeSeconds / 60);
  const remainder = safeSeconds % 60;
  return `${minutes}:${remainder.toString().padStart(2, "0")}`;
}

export function AptitudeTab() {
  const {
    interviewId,
    roundRestartKeys,
    aptitudeQuestions,
    aptitudeAnswers,
    aptitudeResult,
    addAptitudeAnswer,
    setAptitudeResult,
    addExecutionLog,
    progressToNextStep,
    setCurrentStep,
    backendWorkflowEnabled,
    workflowState,
  } = useInterviewStore();
  const { advanceWorkflowOrFallback, refreshWorkflowState, isNextStepAllowed } = useWorkflowActions();
  const autoSaveAnswers = useSettingsStore((state) => state.settings.interview.autoSaveAnswers);

  const [answers, setAnswers] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      aptitudeAnswers.map((answer) => [answer.questionId, String(answer.selectedOption || "")])
    )
  );
  const [startedAt, setStartedAt] = useState(() => Date.now());
  const [remainingSeconds, setRemainingSeconds] = useState(APTITUDE_ROUND_LIMIT_SECONDS);
  const [roundTimedOut, setRoundTimedOut] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitConfirmOpen, setSubmitConfirmOpen] = useState(false);
  const autoSubmitTriggeredRef = useRef(false);
  const result = aptitudeResult;
  const backendBlocksTechnical =
    backendWorkflowEnabled && Boolean(workflowState) && !isNextStepAllowed("technical");

  useEffect(() => {
    const now = Date.now();
    setStartedAt(now);
    setRemainingSeconds(APTITUDE_ROUND_LIMIT_SECONDS);
    setRoundTimedOut(false);
    autoSubmitTriggeredRef.current = false;
  }, [interviewId, roundRestartKeys.aptitude]);

  useEffect(() => {
    if (!interviewId || aptitudeQuestions.length === 0 || result) return;

    const tick = () => {
      const elapsedSeconds = Math.floor((Date.now() - startedAt) / 1000);
      const nextRemaining = Math.max(0, APTITUDE_ROUND_LIMIT_SECONDS - elapsedSeconds);
      setRemainingSeconds(nextRemaining);
      if (nextRemaining === 0) setRoundTimedOut(true);
    };

    tick();
    const interval = window.setInterval(tick, 1000);
    return () => window.clearInterval(interval);
  }, [aptitudeQuestions.length, interviewId, result, startedAt]);

  useEffect(() => {
    if (!autoSaveAnswers || !interviewId || result) return;
    const saved = readAutosavedValue<Record<string, string>>(interviewId, "aptitude-answers", {});
    if (Object.keys(saved).length > 0) {
      setAnswers((current) => ({ ...saved, ...current }));
    }
  }, [autoSaveAnswers, interviewId, result]);

  useEffect(() => {
    if (!interviewId) return;
    if (!autoSaveAnswers || result) {
      clearAutosavedValue(interviewId, "aptitude-answers");
      return;
    }

    if (Object.keys(answers).length > 0) {
      writeAutosavedValue(interviewId, "aptitude-answers", answers);
    }
  }, [answers, autoSaveAnswers, interviewId, result]);

  const answeredCount = useMemo(
    () => aptitudeQuestions.filter((question) => answers[question.id]).length,
    [answers, aptitudeQuestions]
  );
  const displaySeed = `${interviewId || "new"}:${roundRestartKeys.aptitude}`;
  const displayedQuestions = useMemo(
    () => seededShuffle(aptitudeQuestions, `${displaySeed}:questions`),
    [aptitudeQuestions, displaySeed]
  );
  const displayedOptionsByQuestion = useMemo(
    () =>
      Object.fromEntries(
        displayedQuestions.map((question) => [question.id, displayOptionEntries(question, displaySeed)])
      ),
    [displaySeed, displayedQuestions]
  );

  const resultByQuestion = useMemo(() => {
    const lookup: Record<string, AptitudeRoundResult["per_question_results"][number]> = {};
    result?.per_question_results.forEach((item) => {
      lookup[item.question_id] = item;
    });
    return lookup;
  }, [result]);

  const unanswered = aptitudeQuestions.length - answeredCount;
  const submitConfirmDescription =
    unanswered > 0
      ? `Submit aptitude now? ${unanswered} unanswered question${unanswered === 1 ? "" : "s"} will be marked wrong.`
      : "Submit aptitude answers for final scoring?";
  const timerIsCritical = remainingSeconds <= 60 && !result;
  const timerLabel = result
    ? "Aptitude complete"
    : roundTimedOut
    ? "Time expired"
    : `${formatRoundDuration(remainingSeconds)} left`;

  const requestSubmitAnswers = () => {
    if (!interviewId || aptitudeQuestions.length === 0 || result) return;
    setSubmitConfirmOpen(true);
  };

  const submitAnswers = useCallback(
    async (source: "manual" | "timeout" = "manual") => {
    if (!interviewId || aptitudeQuestions.length === 0 || result || isSubmitting) return;

    setSubmitConfirmOpen(false);
    setIsSubmitting(true);

    try {
      const valueAwareAnswers = Object.fromEntries(
        aptitudeQuestions.map((question) => {
          const option = answers[question.id] || "";
          return [
            question.id,
            {
              option,
              value: optionValueForKey(question, option),
            },
          ];
        })
      );
      const response = await retryRequest({
        request: () =>
          apiService.request<AptitudeRoundResult>("/api/aptitude/submit", {
            method: "POST",
            timeoutMs: 35_000,
            body: {
              interview_id: interviewId,
              answers: valueAwareAnswers,
              time_taken_seconds: Math.min(APTITUDE_ROUND_LIMIT_SECONDS, Math.round((Date.now() - startedAt) / 1000)),
            },
          }),
        onRetry: (_error, attempt) => {
          addExecutionLog({
            type: "warning",
            agent: "Aptitude Agent",
            message: `Aptitude scoring is retrying after a transient backend delay (${attempt + 1}/3).`,
          });
        },
      });

      aptitudeQuestions.forEach((question) => {
        addAptitudeAnswer({
          questionId: question.id,
          selectedOption: answers[question.id] || "",
          timestamp: new Date(),
        });
      });
      addExecutionLog({
        type: response.score >= 70 ? "success" : "warning",
        agent: "Aptitude Agent",
        message:
          source === "timeout"
            ? `Aptitude time expired. Auto-submitted answers scored ${Math.round(response.score)}/100.`
            : `Aptitude scored ${Math.round(response.score)}/100.`,
      });
      setAptitudeResult(response);
      void refreshWorkflowState();
      addExecutionLog({
        type: "success",
        agent: "Interview Flow",
        message:
          source === "timeout"
            ? "Aptitude auto-submit complete. Review your score, then continue to Technical."
            : "Aptitude submitted. Review your score, then continue when ready.",
      });
    } catch (error) {
      addExecutionLog({
        type: "error",
        agent: "Aptitude Agent",
        message: error instanceof Error ? error.message : "Unable to submit aptitude answers.",
      });
    } finally {
      setIsSubmitting(false);
    }
    },
    [
      addAptitudeAnswer,
      addExecutionLog,
      answers,
      aptitudeQuestions,
      interviewId,
      isSubmitting,
      refreshWorkflowState,
      result,
      setAptitudeResult,
      startedAt,
    ]
  );

  useEffect(() => {
    if (!roundTimedOut || result || autoSubmitTriggeredRef.current) return;
    autoSubmitTriggeredRef.current = true;
    addExecutionLog({
      type: "warning",
      agent: "Interview Flow",
      message: "Aptitude round time expired. Auto-submitting answers for scoring.",
    });
    void submitAnswers("timeout");
  }, [addExecutionLog, result, roundTimedOut, submitAnswers]);

  if (!interviewId || aptitudeQuestions.length === 0) {
    return (
      <Card className="bg-surface-1 border-hairline">
        <CardContent className="py-16 text-center">
          <Brain className="mx-auto mb-4 h-10 w-10 text-ink-muted" />
          <h3 className="mb-2 text-headline text-ink">Start an interview first</h3>
          <p className="mx-auto mb-6 max-w-xl text-body text-ink-muted">
            Submit the form and complete the DSA round before answering aptitude questions.
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
      <div className="grid h-full min-h-0 grid-cols-1 gap-6 overflow-hidden xl:grid-cols-[minmax(0,1fr)_320px]">
      <Card className="flex min-h-0 flex-col overflow-hidden bg-surface-1 border-hairline">
        <CardHeader>
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div>
              <CardTitle className="text-headline text-ink">Aptitude Round</CardTitle>
              <p className="mt-1 text-body-sm text-ink-muted">
                Answer the generated reasoning set and submit it for scoring.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge
                variant="outline"
                className={cn(
                  "w-fit gap-1 border-hairline text-ink-muted",
                  timerIsCritical && "border-gradient-coral text-gradient-coral",
                  result && "border-semantic-success text-semantic-success"
                )}
              >
                <Timer className="h-3.5 w-3.5" />
                {timerLabel}
              </Badge>
              <Badge variant="outline" className="w-fit border-hairline text-ink-muted">
                {answeredCount}/{aptitudeQuestions.length} answered
              </Badge>
            </div>
          </div>
        </CardHeader>
        <CardContent className="min-h-0 flex-1 space-y-5 overflow-y-auto">
          {displayedQuestions.map((question, index) => {
            const evaluation = resultByQuestion[question.id];
            return (
              <div key={question.id} className="rounded-lg border border-hairline bg-surface-2 p-4">
                <div className="mb-3 flex items-start justify-between gap-3">
                  <div>
                    <p className="text-caption text-ink-muted">Question {index + 1}</p>
                    <h4 className="mt-1 text-body font-medium text-ink">{questionText(question)}</h4>
                  </div>
                  {question.category && (
                    <Badge variant="outline" className="border-hairline text-ink-muted">
                      {cleanGeneratedText(question.category)}
                    </Badge>
                  )}
                </div>

                <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                  {(displayedOptionsByQuestion[question.id] || []).map(({ displayKey, originalKey, value }) => {
                    const isSelected = answers[question.id] === originalKey;
                    const acceptedOptions = acceptedOptionsFor(evaluation);
                    const acceptedValues = acceptedValuesFor(evaluation);
                    const isCorrect =
                      Boolean(evaluation) &&
                      (acceptedOptions.has(originalKey) ||
                        acceptedValues.some((acceptedValue) => answerValuesMatch(acceptedValue, value)));
                    const isWrongSelection = Boolean(evaluation && isSelected && !evaluation.is_correct && !isCorrect);
                    return (
                      <button
                        key={originalKey}
                        type="button"
                        onClick={() =>
                          !result &&
                          !isSubmitting &&
                          setAnswers((current) => ({
                            ...current,
                            [question.id]: originalKey,
                          }))
                        }
                        className={cn(
                          "flex min-h-14 items-center gap-3 rounded-lg border p-3 text-left text-body-sm transition-colors",
                          isSelected ? "border-accent-blue bg-black/20 text-ink" : "border-hairline text-ink-muted",
                          evaluation && isCorrect && "border-semantic-success text-semantic-success",
                          evaluation && isWrongSelection && "border-gradient-coral text-gradient-coral"
                        )}
                      >
                        {isSelected ? (
                          <CheckCircle2 className="h-4 w-4 flex-shrink-0" />
                        ) : (
                          <Circle className="h-4 w-4 flex-shrink-0" />
                        )}
                        <span className="font-medium">{displayKey}.</span>
                        <span>{value}</span>
                      </button>
                    );
                  })}
                </div>

                {evaluation && (
                  <p className="mt-3 text-caption text-ink-muted">
                    {cleanGeneratedText(evaluation.explanation)}
                  </p>
                )}
              </div>
            );
          })}

          <div className="flex flex-col gap-3 sm:flex-row">
            <Button
              onClick={requestSubmitAnswers}
              disabled={isSubmitting || Boolean(result)}
              className="rounded-pill bg-primary text-on-primary hover:bg-primary/90"
            >
              {isSubmitting ? (
                "Scoring..."
              ) : (
                <>
                  <Send className="mr-2 h-4 w-4" />
                  Submit Aptitude
                </>
              )}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => void advanceWorkflowOrFallback(progressToNextStep)}
              disabled={!result || backendBlocksTechnical}
              className="rounded-pill border-hairline"
            >
              Continue to Technical
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card className="flex min-h-0 flex-col overflow-hidden bg-surface-1 border-hairline">
        <CardHeader>
          <CardTitle className="text-headline text-ink">Score</CardTitle>
        </CardHeader>
        <CardContent className="min-h-0 flex-1 overflow-y-auto">
          {result ? (
            <div className="space-y-4">
              <div className="rounded-lg border border-hairline bg-surface-2 p-4">
                <p className="text-caption text-ink-muted">Aptitude score</p>
                <p className="mt-2 text-display-md text-ink">{Math.round(result.score)}/100</p>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-lg border border-hairline bg-surface-2 p-3">
                  <p className="text-caption text-ink-muted">Correct</p>
                  <p className="text-headline text-semantic-success">{result.correct}</p>
                </div>
                <div className="rounded-lg border border-hairline bg-surface-2 p-3">
                  <p className="text-caption text-ink-muted">Needs review</p>
                  <p className="text-headline text-gradient-coral">{result.wrong}</p>
                </div>
              </div>
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-hairline p-6 text-center">
              <p className="text-body-sm text-ink-muted">
                Submit all answers to see the round score.
              </p>
            </div>
          )}
        </CardContent>
      </Card>
      </div>

      <InAppConfirmDialog
        open={submitConfirmOpen}
        title="Submit Aptitude Answers"
        description={submitConfirmDescription}
        confirmLabel="Submit Answers"
        onOpenChange={setSubmitConfirmOpen}
        onConfirm={() => void submitAnswers()}
      />
    </>
  );
}
