"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { apiService } from "@/services/api-service";
import { cleanGeneratedText } from "@/lib/generated-text";
import { cn } from "@/lib/utils";
import { useSettingsStore } from "@/stores/settings-store";
import type { UserSettings } from "@/types";
import { Brain, CheckCircle2, Code, History, Loader2, Shuffle, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

const modes = [
  {
    icon: Code,
    title: "DSA Practice",
    type: "dsa",
    description: "fresh MCQs on algorithms, complexity, patterns, and edge cases",
    color: "from-gradient-violet to-gradient-magenta",
  },
  {
    icon: Brain,
    title: "Aptitude Practice",
    type: "aptitude",
    description: "fresh MCQs across logic, quant, reasoning, and data interpretation",
    color: "from-gradient-magenta to-gradient-coral",
  },
  {
    icon: Shuffle,
    title: "Mixed Rounds",
    type: "mixed",
    description: "fresh MCQs mixing DSA-style reasoning with aptitude",
    color: "from-gradient-orange to-gradient-coral",
  },
];

type PracticeQuestion = {
  id: string;
  question_text?: string;
  question?: string;
  options: Record<string, string> | string[];
  category?: string;
  difficulty?: string;
  explanation?: string;
};

type PracticeSession = {
  id: string;
  mode: string;
  difficulty: string;
  startedAt: string;
  endedAt?: string | null;
  score: number;
  questions: PracticeQuestion[];
  results?: PracticeResult | null;
};

type PracticeResult = {
  score: number;
  correct: number;
  wrong: number;
  per_question_results: Array<{
    question_id: string;
    selected?: string;
    correct: string;
    is_correct: boolean;
    explanation: string;
  }>;
};

function optionEntries(options: Record<string, string> | string[]) {
  if (Array.isArray(options)) {
    return options.map((value, index) => [String.fromCharCode(65 + index), cleanGeneratedText(value)] as const);
  }
  return Object.entries(options).map(([key, value]) => [key, cleanGeneratedText(value)] as const);
}

function questionText(question: PracticeQuestion) {
  return cleanGeneratedText(question.question_text || question.question, "Question");
}

function formatDate(value: string) {
  return new Date(value).toLocaleDateString("en", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function clampPracticeQuestionCount(value: unknown) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 20;
  return Math.min(30, Math.max(5, Math.round(parsed)));
}

export default function PracticeArenaPage() {
  const { settings, setSettings } = useSettingsStore();
  const [session, setSession] = useState<PracticeSession | null>(null);
  const [history, setHistory] = useState<PracticeSession[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [result, setResult] = useState<PracticeResult | null>(null);
  const [isStarting, setIsStarting] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");
  const practiceQuestionCount = clampPracticeQuestionCount(settings.interview.practiceQuestionCount);

  const answeredCount = useMemo(() => Object.keys(answers).length, [answers]);
  const resultByQuestion = useMemo(() => {
    const map = new Map<string, PracticeResult["per_question_results"][number]>();
    result?.per_question_results.forEach((item) => map.set(item.question_id, item));
    return map;
  }, [result]);

  const loadHistory = async () => {
    try {
      const response = await apiService.request<PracticeSession[]>("/api/practice/sessions");
      setHistory(response);
    } catch {
      // History is helpful, but practice can still start without it.
    }
  };

  useEffect(() => {
    loadHistory();
    apiService
      .request<UserSettings>("/api/settings", { cacheTtlMs: 30_000 })
      .then(setSettings)
      .catch(() => undefined);
  }, [setSettings]);

  const startPractice = async (type: string) => {
    setIsStarting(type);
    setError("");
    setAnswers({});
    setResult(null);
    try {
      const response = await apiService.request<{ session: PracticeSession }>("/api/practice/session/start", {
        method: "POST",
        body: { type, difficulty: "medium", question_count: practiceQuestionCount },
      });
      setSession(response.session);
      await loadHistory();
    } catch (startError) {
      setError(startError instanceof Error ? startError.message : "Unable to start practice");
    } finally {
      setIsStarting(null);
    }
  };

  const submitPractice = async () => {
    if (!session) return;
    setIsSubmitting(true);
    setError("");
    try {
      const response = await apiService.request<PracticeResult>(`/api/practice/session/${session.id}/submit`, {
        method: "POST",
        body: { answers },
      });
      setResult(response);
      setSession({ ...session, score: response.score, endedAt: new Date().toISOString(), results: response });
      await loadHistory();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Unable to submit practice");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-display-lg text-ink mb-2">Practice Arena</h1>
        <p className="text-body text-ink-muted">
          Start fresh {practiceQuestionCount}-question MCQ sessions and review your saved practice history
        </p>
      </div>

      {error && (
        <Card className="border-hairline bg-surface-1">
          <CardContent className="py-4 text-body-sm text-gradient-coral">{error}</CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
        {modes.map((mode) => (
          <Card key={mode.type} className="bg-surface-1 border-hairline hover:border-accent-blue/50 transition-colors">
            <CardContent className="pt-6">
              <div className={`w-12 h-12 rounded-lg bg-gradient-to-br ${mode.color} flex items-center justify-center mb-4`}>
                <mode.icon className="w-6 h-6 text-ink" />
              </div>
              <h3 className="text-headline text-ink mb-2">{mode.title}</h3>
              <p className="text-body text-ink-muted mb-6">
                {practiceQuestionCount} {mode.description}
              </p>
              <Button
                onClick={() => startPractice(mode.type)}
                disabled={isStarting === mode.type}
                className="w-full bg-primary text-on-primary rounded-lg"
              >
                {isStarting === mode.type && <Loader2 className="h-4 w-4 animate-spin" />}
                {isStarting === mode.type ? "Generating..." : "Start Practice"}
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>

      {session && (
        <Card className="border-hairline bg-surface-1">
          <CardHeader>
            <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
              <div>
                <CardTitle className="text-headline text-ink">
                  {session.mode.toUpperCase()} Practice Session
                </CardTitle>
                <p className="mt-1 text-body-sm text-ink-muted">
                  {session.questions.length} MCQs generated {formatDate(session.startedAt)}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Badge variant="outline" className="border-hairline text-ink-muted">
                  {answeredCount}/{session.questions.length} answered
                </Badge>
                {result && <Badge className="bg-primary text-on-primary">{Math.round(result.score)}%</Badge>}
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-5">
            <Progress value={(answeredCount / Math.max(session.questions.length, 1)) * 100} className="h-2" />

            <div className="space-y-4">
              {session.questions.map((question, index) => {
                const questionResult = resultByQuestion.get(question.id);
                return (
                  <div key={question.id} className="rounded-lg border border-hairline bg-surface-2 p-4">
                    <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <p className="text-caption text-ink-muted">Question {index + 1}</p>
                        <h3 className="mt-1 text-body font-semibold text-ink">
                          {questionText(question)}
                        </h3>
                      </div>
                      <Badge variant="outline" className="border-hairline text-ink-muted">
                        {cleanGeneratedText(question.category || session.mode)}
                      </Badge>
                    </div>

                    <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                      {optionEntries(question.options).map(([key, value]) => {
                        const selected = answers[question.id] === key;
                        const isCorrectAnswer = questionResult?.correct === key;
                        const isWrongSelection = questionResult && selected && !questionResult.is_correct;

                        return (
                          <button
                            key={key}
                            onClick={() =>
                              !result &&
                              setAnswers((current) => ({
                                ...current,
                                [question.id]: key,
                              }))
                            }
                            disabled={Boolean(result)}
                            className={cn(
                              "flex items-start gap-3 rounded-md border border-hairline bg-surface-1 p-3 text-left text-body-sm transition-colors",
                              selected && "border-accent-blue",
                              isCorrectAnswer && "border-semantic-success",
                              isWrongSelection && "border-gradient-coral"
                            )}
                          >
                            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-hairline text-caption text-ink-muted">
                              {key}
                            </span>
                            <span className="text-ink-muted">{value}</span>
                          </button>
                        );
                      })}
                    </div>

                    {questionResult && (
                      <div className="mt-4 flex gap-2 rounded-md border border-hairline bg-surface-1 p-3 text-body-sm text-ink-muted">
                        {questionResult.is_correct ? (
                          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-semantic-success" />
                        ) : (
                          <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-gradient-coral" />
                        )}
                        <span>{cleanGeneratedText(questionResult.explanation)}</span>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            {!result && (
              <div className="sticky bottom-4 flex justify-end">
                <Button
                  onClick={submitPractice}
                  disabled={isSubmitting || answeredCount === 0}
                  className="bg-primary text-on-primary rounded-lg"
                >
                  {isSubmitting && <Loader2 className="h-4 w-4 animate-spin" />}
                  Submit Practice
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <Card className="border-hairline bg-surface-1">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-headline text-ink">
            <History className="h-5 w-5 text-accent-blue" />
            Practice History
          </CardTitle>
        </CardHeader>
        <CardContent>
          {history.length === 0 ? (
            <p className="text-body-sm text-ink-muted">No practice sessions saved yet.</p>
          ) : (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {history.slice(0, 9).map((item) => (
                <button
                  key={item.id}
                  onClick={() => {
                    setSession(item);
                    setResult(item.results || null);
                    setAnswers({});
                  }}
                  className="rounded-lg border border-hairline bg-surface-2 p-4 text-left transition-colors hover:border-accent-blue/60"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-body font-semibold text-ink">{item.mode.toUpperCase()}</p>
                      <p className="mt-1 text-caption text-ink-muted">{formatDate(item.startedAt)}</p>
                    </div>
                    <Badge variant="outline" className="border-hairline text-ink-muted">
                      {item.endedAt ? `${Math.round(item.score)}%` : "In progress"}
                    </Badge>
                  </div>
                  <p className="mt-3 text-body-sm text-ink-muted">{item.questions.length} questions</p>
                </button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
