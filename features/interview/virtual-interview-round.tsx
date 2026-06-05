"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import Editor from "@monaco-editor/react";
import Image from "next/image";
import {
  AlertTriangle,
  Bot,
  Camera,
  CameraOff,
  CheckCircle2,
  Code2,
  Loader2,
  Maximize2,
  Mic,
  MicOff,
  PauseCircle,
  PhoneOff,
  Play,
  Repeat2,
  Send,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Timer,
  Volume2,
  Wifi,
  WifiOff,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { getCodeLanguage } from "@/constants/code-languages";
import { getInterviewVoiceProfile } from "@/constants/voice-profiles";
import { useWorkflowActions } from "@/hooks/use-workflow-state";
import { clearAutosavedValue, readAutosavedValue, writeAutosavedValue } from "@/lib/interview-autosave";
import { cleanGeneratedText } from "@/lib/generated-text";
import { cn } from "@/lib/utils";
import { apiService } from "@/services/api-service";
import { useInterviewStore } from "@/stores/interview-store";
import { useSettingsStore } from "@/stores/settings-store";
import type { AnswerRoundResult, InterviewQuestion, ProctorEvent, SpeechMetrics } from "@/types";
import { InterviewLiveKitAudioLayer } from "./realtime/livekit-audio-layer";
import { InAppConfirmDialog } from "./in-app-confirm-dialog";
import { blockEditorClipboardEvent, installMonacoClipboardGuard } from "./editor-clipboard-guard";
import {
  type CaptureMode,
  type MediaEventType,
  useRealtimeInterviewSession,
} from "./realtime/use-realtime-interview-session";
import {
  answerTextWithoutPassCommand,
  commandFromSpeech,
  isSubstantiveAnswerText,
} from "./voice-command-intents";

type Round = "technical" | "hr";
type Phase = "lobby" | "active" | "evaluation" | "terminated";
type AnswerMode = "spoken" | "code";
type FullscreenBlock = { mode: "recover" | "end"; message: string } | null;
type EndCallConfirmMode = "locked" | "manual";

type RoundRuntimeResponse = {
  runtime: {
    status: "not_started" | "in_progress" | "awaiting_follow_up" | "completed" | "terminated";
    currentIndex: number | null;
    currentQuestionId: string | null;
    timer: {
      startedAt: string | null;
      timerSeconds: number;
      expiresAt: string | null;
    };
    adaptationSignals?: Record<string, unknown>;
  };
  currentQuestion: InterviewQuestion | null;
  followUpPrompt?: string | null;
  allowedActions: string[];
  events: Array<Record<string, unknown>>;
};

interface VirtualInterviewRoundProps {
  title: string;
  description: string;
  emptyMessage: string;
  questions: InterviewQuestion[];
  round: Round;
  agentName: string;
  endpoint: string;
  nextLabel: string;
  onComplete: () => void | Promise<void>;
  completionDisabled?: boolean;
  completionContent?: ReactNode;
}

type TranscriptLine = {
  id: string;
  speaker: "bot" | "user" | "system";
  text: string;
  questionId?: string;
  timestamp: Date;
};

type RealtimeSpeechSignal = {
  type: "non_answer" | "off_topic" | "unsafe" | "low_relevance" | "substantive";
  severity: "info" | "warning" | "critical";
  message: string;
  timestamp: string;
  excerpt?: string;
};

type MetricDraft = {
  startedAt: number;
  lastSpeechAt: number | null;
  confidenceSamples: number[];
  words: number;
  longPauseCount: number;
  unclearCount: number;
  realtimeSignals: RealtimeSpeechSignal[];
};

const BOT_PROFILES = {
  technical: {
    name: "Ava",
    role: "technical interviewer",
    asset: "/bot-interviewer.png",
    accent: "Technical Agent",
  },
  hr: {
    name: "Mira",
    role: "HR interviewer",
    asset: "/hr-interviewer.png",
    accent: "HR Agent",
  },
} satisfies Record<Round, { name: string; role: string; asset: string; accent: string }>;

function nowId(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function questionText(question?: InterviewQuestion) {
  return cleanGeneratedText(question?.question_text, "Question").replace(
    /^(?:question|q)\s*\d+\s*[:.)-]?\s*/i,
    ""
  );
}

function wordCount(text: string) {
  return text.trim().split(/\s+/).filter(Boolean).length;
}

function formatClock(seconds: number) {
  const safeSeconds = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(safeSeconds / 60);
  const remainder = safeSeconds % 60;
  return `${minutes}:${remainder.toString().padStart(2, "0")}`;
}

function answerModeFor(round: Round, question: InterviewQuestion, index: number): AnswerMode {
  if (question.answer_mode === "code" || question.answer_mode === "spoken") return question.answer_mode;
  return round === "technical" && index >= 3 ? "code" : "spoken";
}

function timerSecondsFor(round: Round, question: InterviewQuestion, index: number) {
  if (question.timer_seconds) return question.timer_seconds;
  const mode = answerModeFor(round, question, index);
  if (mode === "code") return 10 * 60;
  const difficulty = String(question.difficulty || "").toLowerCase();
  if (difficulty === "hard") return 5 * 60;
  if (difficulty === "medium") return 4 * 60;
  return 3 * 60;
}

function buildMetrics(draft: MetricDraft | undefined, answer: string, fallbackStartedAt: number): SpeechMetrics {
  const startedAt = draft?.startedAt || fallbackStartedAt || Date.now();
  const durationSeconds = Math.max(1, Math.round((Date.now() - startedAt) / 1000));
  const words = Math.max(draft?.words || 0, wordCount(answer));
  const hasCapturedAnswer = answer.trim().length > 0 || words > 0;
  const realtimeSignals = draft?.realtimeSignals || [];
  const hasNonAnswerSignal = realtimeSignals.some((signal) => signal.type === "non_answer");
  const hasUnsafeSignal = realtimeSignals.some((signal) => signal.type === "unsafe");
  const lowRelevanceSignals = realtimeSignals.filter((signal) => signal.type === "low_relevance" || signal.type === "off_topic").length;
  const averageConfidence =
    draft?.confidenceSamples.length
      ? draft.confidenceSamples.reduce((sum, value) => sum + value, 0) / draft.confidenceSamples.length
      : hasCapturedAnswer
      ? 0.72
      : 0;
  const wordsPerMinute = Math.round((words / durationSeconds) * 60);
  const longPauseCount = draft?.longPauseCount || 0;
  const unclearCount = draft?.unclearCount || 0;
  const notes: string[] = [];

  if (!hasCapturedAnswer) notes.push("No speech was captured for this question.");
  else if (averageConfidence < 0.65) notes.push("Speech recognition confidence was low.");
  if (longPauseCount > 0) notes.push(`${longPauseCount} long pause${longPauseCount > 1 ? "s" : ""} detected.`);
  if (wordsPerMinute > 0 && wordsPerMinute < 70) notes.push("Answer pace was slow, suggesting hesitation or lag.");
  if (unclearCount > 0) notes.push("The bot had to ask for clearer speech.");
  if (hasNonAnswerSignal) notes.push("Realtime listener detected this as a non-answer.");
  if (hasUnsafeSignal) notes.push("Realtime listener detected unprofessional or unsafe language.");
  if (lowRelevanceSignals > 0) notes.push("Realtime listener detected possible low relevance while the answer was spoken.");
  if (notes.length === 0) notes.push("Speech delivery was steady based on captured realtime transcript signals.");

  let confidenceLabel: SpeechMetrics["confidenceLabel"] = "steady";
  if (!answer.trim() || hasNonAnswerSignal || hasUnsafeSignal || averageConfidence < 0.45 || unclearCount >= 3) {
    confidenceLabel = "unclear";
  } else if (averageConfidence < 0.65 || longPauseCount >= 2 || (wordsPerMinute > 0 && wordsPerMinute < 70)) {
    confidenceLabel = "hesitant";
  } else if (averageConfidence >= 0.82 && longPauseCount === 0 && wordsPerMinute >= 80) {
    confidenceLabel = "strong";
  }

  return {
    averageConfidence: Number(averageConfidence.toFixed(2)),
    wordsPerMinute,
    durationSeconds,
    longPauseCount,
    unclearCount,
    transcriptWords: words,
    confidenceLabel,
    notes,
    realtimeSignals,
  };
}

function emptySpeechMetrics(note = "No speech was captured for this question."): SpeechMetrics {
  return {
    averageConfidence: 0,
    wordsPerMinute: 0,
    durationSeconds: 0,
    longPauseCount: 0,
    unclearCount: 0,
    transcriptWords: 0,
    confidenceLabel: "unclear",
    notes: [note],
    realtimeSignals: [],
  };
}

function codeAnswerMetrics(answer: string, fallbackStartedAt: number): SpeechMetrics {
  const startedAt = fallbackStartedAt || Date.now();
  const durationSeconds = Math.max(1, Math.round((Date.now() - startedAt) / 1000));
  const codeLines = answer.split(/\r?\n/).filter((line) => line.trim()).length;
  const hasCode = answer.trim().length > 0;
  return {
    averageConfidence: hasCode ? 1 : 0,
    wordsPerMinute: 0,
    durationSeconds,
    longPauseCount: 0,
    unclearCount: 0,
    transcriptWords: wordCount(answer),
    confidenceLabel: hasCode ? "steady" : "unclear",
    notes: [
      hasCode
        ? `Code answer submitted with ${codeLines} non-empty line${codeLines === 1 ? "" : "s"}. Speech delivery was not used for scoring.`
        : "No code was submitted. Speech delivery was not used for scoring.",
    ],
    realtimeSignals: [],
  };
}

function tokenSet(value: string) {
  return new Set((value.toLowerCase().match(/[a-z][a-z0-9+#-]*/g) || []).filter((token) => token.length > 2));
}

function realtimeSpeechSignal(text: string, question: InterviewQuestion | undefined, round: Round): RealtimeSpeechSignal | null {
  const cleanText = cleanGeneratedText(text);
  const normalized = cleanText.toLowerCase();
  const words = wordCount(cleanText);
  if (!cleanText) return null;
  if (commandFromSpeech(cleanText) === "dont_know") {
    return {
      type: "non_answer",
      severity: "warning",
      message: "Candidate indicated they do not know the answer.",
      timestamp: new Date().toISOString(),
      excerpt: cleanText.slice(0, 180),
    };
  }

  if (/\b(fuck|fucking|shit|bitch|bastard|idiot|stupid|shut up|moron|asshole)\b/i.test(cleanText)) {
    return {
      type: "unsafe",
      severity: "critical",
      message: "Unprofessional or abusive language was detected during the answer.",
      timestamp: new Date().toISOString(),
      excerpt: cleanText.slice(0, 180),
    };
  }

  if (!question || words < 18) return null;
  const answerTokens = tokenSet(cleanText);
  const questionTokens = tokenSet(questionText(question));
  const keywords = (question.keywords || []).flatMap((keyword) => Array.from(tokenSet(keyword)));
  const keywordHits = keywords.filter((keyword) => answerTokens.has(keyword));
  const overlap =
    questionTokens.size > 0
      ? Array.from(questionTokens).filter((token) => answerTokens.has(token)).length / questionTokens.size
      : 0;
  const domainTokens =
    round === "technical"
      ? ["api", "database", "system", "scale", "latency", "test", "debug", "design", "tradeoff", "complexity", "code", "cache"]
      : ["team", "conflict", "stakeholder", "impact", "feedback", "owned", "learned", "deadline", "communicated", "result"];
  const hasDomainSignal = domainTokens.some((token) => answerTokens.has(token));
  const unrelatedHint = /\b(movie|song|food|weather|game|cricket|football|shopping|vacation|random|anything else)\b/i.test(cleanText);

  if (unrelatedHint && overlap < 0.08 && keywordHits.length === 0 && !hasDomainSignal) {
    return {
      type: "off_topic",
      severity: "warning",
      message: "Answer appears off-topic compared with the current question.",
      timestamp: new Date().toISOString(),
      excerpt: cleanText.slice(0, 180),
    };
  }

  if (words >= 30 && overlap < 0.05 && keywordHits.length === 0 && !hasDomainSignal) {
    return {
      type: "low_relevance",
      severity: "warning",
      message: "Realtime relevance is low so far; answer should connect back to the question.",
      timestamp: new Date().toISOString(),
      excerpt: cleanText.slice(0, 180),
    };
  }

  return null;
}

function resultAnswerText(result?: AnswerRoundResult) {
  const answer = (result as (AnswerRoundResult & { answer?: unknown }) | undefined)?.answer;
  return typeof answer === "string" ? answer.trim() : "";
}

function hasCapturedResultAnswer(result: AnswerRoundResult | undefined, localAnswer: string, metrics?: SpeechMetrics) {
  return Boolean(resultAnswerText(result) || localAnswer.trim() || (metrics?.transcriptWords || 0) > 0);
}

function answerStatusLabel(mode: AnswerMode, result: AnswerRoundResult | undefined, localAnswer: string, metrics?: SpeechMetrics) {
  const source = result?.answerSource || "";
  const hasAnswer = hasCapturedResultAnswer(result, localAnswer, metrics);
  if (source === "pass") return "Passed";
  if (source === "dont_know") return "Don't know";
  if (source === "end_call") return hasAnswer ? "Call ended" : "Call ended - skipped";
  if (source === "timer_expired" || result?.timerExpired) return hasAnswer ? "Time expired" : "Time expired - no answer";
  if (mode === "code") return hasAnswer ? "Code answer" : "No code submitted";
  return hasAnswer ? "Spoken answer" : "No speech captured";
}

function fallbackParaphrase(text: string) {
  return `In simpler terms: ${text} Please explain your approach clearly, mention tradeoffs, and give a specific example if it helps.`;
}

function prepareSpeechText(text: string) {
  const replacements: Array<[RegExp, string]> = [
    [/\bUI\b/g, "U I"],
    [/\bUX\b/g, "U X"],
    [/\bAPI\b/g, "A P I"],
    [/\bDSA\b/g, "D S A"],
    [/\bHR\b/g, "H R"],
    [/\bSQL\b/g, "S Q L"],
    [/\bJSON\b/g, "J son"],
    [/\bHTML\b/g, "H T M L"],
    [/\bCSS\b/g, "C S S"],
    [/\bJWT\b/g, "J W T"],
    [/\bREST\b/g, "rest"],
    [/\bCRUD\b/g, "C R U D"],
    [/\bFAANG\b/g, "fang"],
    [/\bCI\/CD\b/g, "C I C D"],
  ];
  return replacements.reduce((current, [pattern, replacement]) => current.replace(pattern, replacement), text);
}

function pickVoice(voices: SpeechSynthesisVoice[], profile: ReturnType<typeof getInterviewVoiceProfile>) {
  const exact = voices.filter((voice) => voice.lang.toLowerCase() === profile.lang.toLowerCase());
  const family = voices.filter((voice) => voice.lang.toLowerCase().startsWith(profile.lang.slice(0, 2).toLowerCase()));
  const candidates = exact.length ? exact : family.length ? family : voices;
  const femaleHints = [
    ...profile.voiceNameHints,
    "female",
    "woman",
    "zira",
    "jenny",
    "aria",
    "samantha",
    "susan",
    "victoria",
    "karen",
    "moira",
    "tessa",
    "serena",
    "heera",
    "kalpana",
    "raveena",
    "veena",
    "priya",
    "neerja",
    "swara",
  ];
  const maleHints = [" male", "david", "mark", "ravi", "george", "daniel", "alex", "fred", "tom", "guy"];
  const isLikelyMale = (voice: SpeechSynthesisVoice) => {
    const haystack = ` ${voice.name} ${voice.lang} `.toLowerCase();
    return maleHints.some((hint) => haystack.includes(hint));
  };
  const isLikelyFemale = (voice: SpeechSynthesisVoice) => {
    const haystack = `${voice.name} ${voice.lang}`.toLowerCase();
    return femaleHints.some((hint) => haystack.includes(hint));
  };
  return (
    candidates.find((voice) => isLikelyFemale(voice) && !isLikelyMale(voice)) ||
    voices.find((voice) => isLikelyFemale(voice) && !isLikelyMale(voice)) ||
    candidates.find((voice) => !isLikelyMale(voice)) ||
    null
  );
}

export function VirtualInterviewRound({
  title,
  description,
  emptyMessage,
  questions,
  round,
  agentName,
  endpoint,
  nextLabel,
  onComplete,
  completionDisabled = false,
  completionContent,
}: VirtualInterviewRoundProps) {
  const profile = BOT_PROFILES[round];
  const {
    interviewId,
    formData,
    addExecutionLog,
    addTranscriptEntry,
    setAnswerRoundResult,
    clearAnswerRound,
    setCurrentStep,
    setInterviewSessionStatus,
    setNavigationLocked,
    technicalResults,
    hrResults,
  } = useInterviewStore();
  const { refreshWorkflowState } = useWorkflowActions();
  const { settings } = useSettingsStore();
  const voiceProfile = getInterviewVoiceProfile(settings.ai.interviewVoiceProfile);
  const results = round === "technical" ? technicalResults : hrResults;
  const languageConfig = getCodeLanguage(formData.language);

  const callRootRef = useRef<HTMLDivElement | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const previewVideoRef = useRef<HTMLVideoElement | null>(null);
  const phaseRef = useRef<Phase>("lobby");
  const listenModeRef = useRef<CaptureMode>("idle");
  const currentIndexRef = useRef(0);
  const botSpeakingRef = useRef(false);
  const speechResolveRef = useRef<(() => void) | null>(null);
  const speechTokenRef = useRef(0);
  const speechKeepAliveRef = useRef<number | null>(null);
  const submittingRef = useRef<Record<string, boolean>>({});
  const draftsRef = useRef<Record<string, MetricDraft>>({});
  const repeatCountsRef = useRef<Record<string, number>>({});
  const paraphraseCountsRef = useRef<Record<string, number>>({});
  const questionStartedRef = useRef<Record<string, number>>({});
  const lastViolationAtRef = useRef<Record<string, number>>({});
  const violationCountRef = useRef(0);
  const fullscreenBlockRef = useRef<FullscreenBlock>(null);
  const pausedRemainingSecondsRef = useRef<number | null>(null);
  const pausedCodeDialogOpenRef = useRef(false);
  const pausedListenModeRef = useRef<CaptureMode>("idle");
  const finishingRef = useRef(false);
  const pointerLeaveTimerRef = useRef<number | null>(null);
  const warningClearTimerRef = useRef<number | null>(null);
  const codeEditorGuardCleanupRef = useRef<(() => void) | null>(null);
  const transcriptScrollRef = useRef<HTMLDivElement | null>(null);
  const objectDetectionStreakRef = useRef({ phone: 0, multiplePeople: 0 });
  const faceDetectionStreakRef = useRef({ none: 0, multiple: 0 });
  const runtimeStartIndexRef = useRef(0);
  const runtimeTimerSecondsRef = useRef<Record<string, number>>({});
  const askedQuestionSequenceRef = useRef<Record<string, number>>({});
  const nextAskedQuestionNumberRef = useRef(1);
  const lastRealtimeSignalAtRef = useRef<Record<string, number>>({});
  const askQuestionRef = useRef<(index: number) => Promise<void>>(async () => undefined);

  const [phase, setPhase] = useState<Phase>("lobby");
  const [listenMode, setListenModeState] = useState<CaptureMode>("idle");
  const [botSpeaking, setBotSpeaking] = useState(false);
  const [availableVoices, setAvailableVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [currentIndex, setCurrentIndexState] = useState(0);
  const [timerEndsAt, setTimerEndsAt] = useState<number | null>(null);
  const [remainingSeconds, setRemainingSeconds] = useState(0);
  const [transcript, setTranscript] = useState<TranscriptLine[]>([]);
  const [partialTranscript, setPartialTranscript] = useState("");
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [codeAnswers, setCodeAnswers] = useState<Record<string, string>>({});
  const [metricsByQuestion, setMetricsByQuestion] = useState<Record<string, SpeechMetrics>>({});
  const [proctorEvents, setProctorEvents] = useState<ProctorEvent[]>([]);
  const [warningMessage, setWarningMessage] = useState("");
  const [clearSpeechMessage, setClearSpeechMessage] = useState("");
  const [isStarting, setIsStarting] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isCompleting, setIsCompleting] = useState(false);
  const [codeDialogOpen, setCodeDialogOpen] = useState(false);
  const [fullscreenBlock, setFullscreenBlock] = useState<FullscreenBlock>(null);
  const [terminationMessage, setTerminationMessage] = useState("");
  const [lastError, setLastError] = useState("");
  const [endCallConfirmMode, setEndCallConfirmMode] = useState<EndCallConfirmMode | null>(null);

  const selectedQuestion = questions[currentIndex];
  const selectedQuestionId = selectedQuestion?.id || "";
  const selectedMode = selectedQuestion ? answerModeFor(round, selectedQuestion, currentIndex) : "spoken";
  const autoSaveAnswers = settings.interview.autoSaveAnswers;
  const forceFullEvaluation = phase === "evaluation" && finishingRef.current;
  const scoredResultCount = Object.keys(results).filter((questionId) => questions.some((question) => question.id === questionId)).length;
  const submittedCount = forceFullEvaluation ? questions.length : scoredResultCount;
  const allSubmitted = questions.length > 0 && (scoredResultCount >= questions.length || forceFullEvaluation);
  const isRoundBlocked = Boolean(fullscreenBlock);

  const displayedQuestionNumber = selectedQuestionId
    ? askedQuestionSequenceRef.current[selectedQuestionId] || currentIndex + 1
    : currentIndex + 1;

  const setListenMode = useCallback((mode: CaptureMode) => {
    listenModeRef.current = mode;
    setListenModeState(mode);
  }, []);

  const showClipboardWarning = useCallback(() => {
    setWarningMessage("Copy and paste are not allowed inside the interview editor.");
  }, []);

  useEffect(
    () => () => {
      if (warningClearTimerRef.current) window.clearTimeout(warningClearTimerRef.current);
      codeEditorGuardCleanupRef.current?.();
    },
    []
  );

  useEffect(() => {
    if (phase !== "active" || fullscreenBlock || !(warningMessage || clearSpeechMessage || lastError)) return;
    if (warningClearTimerRef.current) window.clearTimeout(warningClearTimerRef.current);
    warningClearTimerRef.current = window.setTimeout(() => {
      setWarningMessage("");
      setClearSpeechMessage("");
      setLastError("");
    }, 3500);
    return () => {
      if (warningClearTimerRef.current) window.clearTimeout(warningClearTimerRef.current);
    };
  }, [clearSpeechMessage, fullscreenBlock, lastError, phase, warningMessage]);

  const setPhaseSynced = useCallback((next: Phase) => {
    phaseRef.current = next;
    setPhase(next);
  }, []);

  const setCurrentIndexSynced = useCallback((next: number) => {
    currentIndexRef.current = next;
    setCurrentIndexState(next);
  }, []);

  useEffect(() => {
    phaseRef.current = phase;
  }, [phase]);

  useEffect(() => {
    if (phase !== "terminated") return;
    setInterviewSessionStatus("stopped");
    setNavigationLocked(false);
  }, [phase, setInterviewSessionStatus, setNavigationLocked]);

  useEffect(() => {
    listenModeRef.current = listenMode;
  }, [listenMode]);

  useEffect(() => {
    currentIndexRef.current = currentIndex;
  }, [currentIndex]);

  useEffect(() => {
    botSpeakingRef.current = botSpeaking;
  }, [botSpeaking]);

  useEffect(() => {
    fullscreenBlockRef.current = fullscreenBlock;
  }, [fullscreenBlock]);

  useEffect(() => {
    if (!autoSaveAnswers || !interviewId) return;
    const savedAnswers = readAutosavedValue<Record<string, string>>(interviewId, `${round}-spoken-answers`, {});
    const savedCodeAnswers = readAutosavedValue<Record<string, string>>(interviewId, `${round}-code-answers`, {});
    if (Object.keys(savedAnswers).length > 0) setAnswers((current) => ({ ...savedAnswers, ...current }));
    if (Object.keys(savedCodeAnswers).length > 0) setCodeAnswers((current) => ({ ...savedCodeAnswers, ...current }));
  }, [autoSaveAnswers, interviewId, round]);

  useEffect(() => {
    if (!interviewId) return;
    const answersScope = `${round}-spoken-answers`;
    const codeScope = `${round}-code-answers`;
    if (!autoSaveAnswers || allSubmitted) {
      clearAutosavedValue(interviewId, answersScope);
      clearAutosavedValue(interviewId, codeScope);
      return;
    }
    if (Object.keys(answers).length > 0) writeAutosavedValue(interviewId, answersScope, answers);
    if (Object.keys(codeAnswers).length > 0) writeAutosavedValue(interviewId, codeScope, codeAnswers);
  }, [allSubmitted, answers, autoSaveAnswers, codeAnswers, interviewId, round]);

  useEffect(() => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
    const loadVoices = () => setAvailableVoices(window.speechSynthesis.getVoices());
    loadVoices();
    window.speechSynthesis.addEventListener("voiceschanged", loadVoices);
    return () => window.speechSynthesis.removeEventListener("voiceschanged", loadVoices);
  }, []);

  const indexForQuestionId = useCallback(
    (questionId?: string | null) => {
      if (!questionId) return -1;
      return questions.findIndex((question) => question.id === questionId);
    },
    [questions]
  );

  const applyRuntimeState = useCallback(
    (runtimeState?: RoundRuntimeResponse | null) => {
      if (!runtimeState) return -1;
      const questionId = runtimeState.currentQuestion?.id || runtimeState.runtime.currentQuestionId;
      const index = indexForQuestionId(questionId);
      if (questionId && runtimeState.runtime.timer.timerSeconds > 0) {
        runtimeTimerSecondsRef.current[questionId] = runtimeState.runtime.timer.timerSeconds;
      }
      if (index >= 0) {
        runtimeStartIndexRef.current = index;
        setCurrentIndexSynced(index);
      }
      return index;
    },
    [indexForQuestionId, setCurrentIndexSynced]
  );

  const recordRuntimeCommand = useCallback(
    async (command: string, question?: InterviewQuestion | null, metadata: Record<string, unknown> = {}) => {
      if (!interviewId) return;
      try {
        const response = await apiService.request<RoundRuntimeResponse>(
          `/api/${round}/interviews/${interviewId}/runtime/commands`,
          {
            method: "POST",
            body: {
              command,
              question_id: question?.id,
              metadata,
            },
          }
        );
        applyRuntimeState(response);
      } catch {
        // Runtime commands are observability/control-plane data; the call should continue if this fails.
      }
    },
    [applyRuntimeState, interviewId, round]
  );

  const addLine = useCallback((line: Omit<TranscriptLine, "id" | "timestamp">) => {
    setTranscript((current) => [
      ...current,
      {
        ...line,
        id: nowId("transcript"),
        timestamp: new Date(),
      },
    ]);
  }, []);

  const cancelBotSpeech = useCallback(() => {
    speechTokenRef.current += 1;
    if (speechKeepAliveRef.current) {
      window.clearInterval(speechKeepAliveRef.current);
      speechKeepAliveRef.current = null;
    }
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
    speechResolveRef.current?.();
    speechResolveRef.current = null;
    botSpeakingRef.current = false;
    setBotSpeaking(false);
  }, []);

  const recordUnclearSpeech = useCallback(() => {
    const question = questions[currentIndexRef.current];
    if (question && draftsRef.current[question.id]) {
      draftsRef.current[question.id].unclearCount += 1;
    }
    setClearSpeechMessage("Please speak clearly and loudly again.");
    window.setTimeout(() => setClearSpeechMessage(""), 3000);
  }, [questions]);

  const speakBot = useCallback(
    (text: string, questionId?: string, listenAfter?: CaptureMode) =>
      new Promise<void>((resolve) => {
        setListenMode("idle");
        speechResolveRef.current?.();
        speechResolveRef.current = null;
        speechTokenRef.current += 1;
        const token = speechTokenRef.current;
        if (typeof window !== "undefined" && "speechSynthesis" in window) {
          window.speechSynthesis.cancel();
        }
        setBotSpeaking(true);
        botSpeakingRef.current = true;
        addLine({ speaker: "bot", text, questionId });
        addTranscriptEntry(
          {
            id: nowId("bot"),
            timestamp: new Date(),
            speaker: "ai",
            text,
            confidence: 1,
          },
          round
        );

        const finish = (force = false) => {
          if (!force && speechTokenRef.current !== token) return;
          if (speechKeepAliveRef.current) {
            window.clearInterval(speechKeepAliveRef.current);
            speechKeepAliveRef.current = null;
          }
          speechResolveRef.current = null;
          if (force || speechTokenRef.current === token) {
            botSpeakingRef.current = false;
            setBotSpeaking(false);
            if (listenAfter && phaseRef.current === "active" && !fullscreenBlockRef.current) {
              setListenMode(listenAfter);
            }
          }
          resolve();
        };
        speechResolveRef.current = () => finish(true);

        if (!settings.ai.voiceEnabled || typeof window === "undefined" || !("speechSynthesis" in window)) {
          globalThis.setTimeout(() => finish(), 500);
          return;
        }

        const utterance = new SpeechSynthesisUtterance(prepareSpeechText(text));
        const selectedVoice = pickVoice(availableVoices, voiceProfile);
        if (selectedVoice) utterance.voice = selectedVoice;
        utterance.lang = selectedVoice?.lang || voiceProfile.lang;
        utterance.rate = voiceProfile.rate;
        utterance.pitch = round === "hr" ? Math.min(2, voiceProfile.pitch + 0.02) : voiceProfile.pitch;
        utterance.onend = () => finish();
        utterance.onerror = () => finish();
        try {
          window.speechSynthesis.resume();
          window.speechSynthesis.speak(utterance);
          speechKeepAliveRef.current = window.setInterval(() => {
            if (speechTokenRef.current !== token || !window.speechSynthesis.speaking || !window.speechSynthesis.paused) return;
            window.speechSynthesis.resume();
          }, 1000);
        } catch {
          finish();
        }
      }),
    [addLine, addTranscriptEntry, availableVoices, round, setListenMode, settings.ai.voiceEnabled, voiceProfile]
  );

  const registerProctorEvent = useCallback(
    (type: ProctorEvent["type"], message: string, severity: ProctorEvent["severity"] = "warning") => {
      if (phaseRef.current !== "active" || finishingRef.current) return;
      if (fullscreenBlockRef.current && type !== "fullscreen") return;

      const now = Date.now();
      const key = `${type}:${message}`;
      if (lastViolationAtRef.current[key] && now - lastViolationAtRef.current[key] < 9000) return;
      lastViolationAtRef.current[key] = now;

      const question = questions[currentIndexRef.current];
      const event: ProctorEvent = {
        id: nowId("proctor"),
        type,
        severity,
        message,
        timestamp: new Date().toISOString(),
        questionId: question?.id,
      };
      setProctorEvents((current) => [...current, event]);
      void recordRuntimeCommand("proctor_event", question, {
        event,
        integrityImpact: severity === "critical" ? 25 : 10,
      });
      addExecutionLog({ type: severity === "critical" ? "error" : "warning", agent: "AI Proctor", message });

      if (type === "cursor") {
        setWarningMessage(message);
        window.setTimeout(() => setWarningMessage(""), 2500);
        return;
      }

      violationCountRef.current += 1;
      if (violationCountRef.current === 1) {
        setWarningMessage(`${message} This is your final warning.`);
      } else {
        const finalMessage = "The interview call ended because a second proctoring violation was detected after the final warning.";
        setTerminationMessage(finalMessage);
        setWarningMessage("");
        finishingRef.current = true;
        cancelBotSpeech();
        setListenMode("idle");
        setPhaseSynced("terminated");
        addExecutionLog({ type: "error", agent: "AI Proctor", message: finalMessage });
      }
    },
    [addExecutionLog, cancelBotSpeech, questions, recordRuntimeCommand, setListenMode, setPhaseSynced]
  );

  const handleMediaEvent = useCallback(
    (event: MediaEventType, metadata: Record<string, unknown> = {}) => {
      const question = questions[currentIndexRef.current];
      void recordRuntimeCommand(event, question, {
        ...metadata,
        cameraEnabled: mediaStateRef.current.cameraEnabled,
        micEnabled: mediaStateRef.current.micEnabled,
      });
      if (event === "camera_off" || event === "camera_stopped" || event === "camera_muted") {
        registerProctorEvent("media", event === "camera_off" ? "Camera was turned off during the call." : "Camera stream changed during the call.");
      }
      if (event === "mic_stopped") {
        addLine({
          speaker: "system",
          text: metadata.autoReconnect ? "Microphone reconnecting..." : "Microphone stream disconnected.",
        });
      }
      if (event === "mic_signal_paused") addLine({ speaker: "system", text: "Microphone signal paused." });
      if (event === "mic_signal_resumed") addLine({ speaker: "system", text: "Microphone signal resumed." });
    },
    [addLine, questions, recordRuntimeCommand, registerProctorEvent]
  );

  const recordRealtimeSignal = useCallback(
    async (question: InterviewQuestion, signal: RealtimeSpeechSignal) => {
      const now = Date.now();
      const key = `${question.id}:${signal.type}:${signal.message}`;
      if (lastRealtimeSignalAtRef.current[key] && now - lastRealtimeSignalAtRef.current[key] < 12000) return;
      lastRealtimeSignalAtRef.current[key] = now;

      const draft = draftsRef.current[question.id];
      if (draft && !draft.realtimeSignals.some((item) => item.type === signal.type && item.message === signal.message)) {
        draft.realtimeSignals.push(signal);
      }

      void recordRuntimeCommand("realtime_speech_signal", question, {
        signal,
        activeEvaluation: true,
      });

      if (signal.type === "unsafe") {
        setWarningMessage(signal.message);
        await speakBot("I need to stop you there. Please keep the answer professional and focused on the interview question.", question.id);
        if (phaseRef.current === "active" && !fullscreenBlockRef.current) setListenMode("answer");
        return;
      }

      if (signal.type === "non_answer") {
        setClearSpeechMessage("I heard that you do not know the answer. I will mark this as no answer and move on.");
        await submitQuestionRef.current(question, currentIndexRef.current, {
          answer: "",
          answerSource: "dont_know",
        });
        return;
      }

      if (signal.type === "off_topic") {
        setClearSpeechMessage("Please connect your answer back to the question.");
        await speakBot("Let me pause you for a moment. Please connect your answer back to the question and give one concrete example.", question.id);
        if (phaseRef.current === "active" && !fullscreenBlockRef.current) setListenMode("answer");
        return;
      }

      if (signal.type === "low_relevance") {
        setClearSpeechMessage("Realtime relevance looks low. Bring the answer back to the question.");
      }
    },
    [recordRuntimeCommand, setListenMode, speakBot]
  );

  const analyzeRealtimeSpeech = useCallback(
    (text: string, source: "partial" | "final") => {
      if (listenModeRef.current !== "answer" || fullscreenBlockRef.current || botSpeakingRef.current) return;
      const question = questions[currentIndexRef.current];
      if (!question || submittingRef.current[question.id]) return;
      const signal = realtimeSpeechSignal(text, question, round);
      if (!signal) return;
      const shouldActNow =
        (source === "final" && signal.type !== "non_answer") ||
        signal.type === "unsafe" ||
        signal.type === "off_topic" ||
        (signal.type === "low_relevance" && wordCount(text) >= 45);
      const draft = draftsRef.current[question.id];
      if (draft && !draft.realtimeSignals.some((item) => item.type === signal.type && item.message === signal.message)) {
        draft.realtimeSignals.push(signal);
      }
      if (shouldActNow) void recordRealtimeSignal(question, signal);
    },
    [questions, recordRealtimeSignal, round]
  );

  const handleFinalSpeech = useCallback(
    async (text: string, rawConfidence: number) => {
      const cleanText = cleanGeneratedText(text);
      if (!cleanText || fullscreenBlockRef.current) return;
      const confidence = Number.isFinite(rawConfidence) && rawConfidence > 0 ? rawConfidence : 0.72;
      const mode = listenModeRef.current;
      const question = questions[currentIndexRef.current];
      const currentAnswerMode = question ? answerModeFor(round, question, currentIndexRef.current) : "spoken";
      const command = commandFromSpeech(cleanText);
      setPartialTranscript("");
      if (currentAnswerMode === "code" && mode !== "consent") return;
      addLine({ speaker: "user", text: cleanText, questionId: question?.id });
      analyzeRealtimeSpeech(cleanText, "final");

      if (mode === "consent") {
        if (command === "yes") {
          setListenMode("idle");
          await speakBot("Great. I will ask one question at a time. Please answer naturally, and I will keep the timer for you.");
          await askQuestionRef.current(runtimeStartIndexRef.current);
          return;
        }
        if (command === "no") {
          await speakBot("No problem. Take a moment. Say yes when you are ready to begin.");
          setListenMode("consent");
          return;
        }
        recordUnclearSpeech();
        await speakBot("I could not confirm that. Please say yes to start, or no if you need a moment.");
        setListenMode("consent");
        return;
      }

      if (mode !== "answer" || !question) return;

      if (command === "dont_know") {
        void recordRuntimeCommand("dont_know", question, { source: "speech" });
        await speakBot("Understood. I will mark this as no answer and move to the next question.", question.id);
        await submitQuestionRef.current(question, currentIndexRef.current, {
          answer: "",
          answerSource: "dont_know",
        });
        return;
      }

      if (command === "repeat") {
        repeatCountsRef.current[question.id] = (repeatCountsRef.current[question.id] || 0) + 1;
        void recordRuntimeCommand("repeat", question, { source: "speech" });
        await speakBot(`Sure. ${questionText(question)}`, question.id);
        setListenMode("answer");
        return;
      }

      if (command === "paraphrase") {
        paraphraseCountsRef.current[question.id] = (paraphraseCountsRef.current[question.id] || 0) + 1;
        void recordRuntimeCommand("paraphrase", question, { source: "speech" });
        const paraphrase = await fetchParaphraseRef.current(question);
        await speakBot(paraphrase, question.id);
        setListenMode("answer");
        return;
      }

      if (command === "pass") {
        const existingAnswer = answersRef.current[question.id] || "";
        const answerRemainder = answerTextWithoutPassCommand(cleanText);
        const combinedAnswer = `${existingAnswer}${existingAnswer && answerRemainder ? " " : ""}${answerRemainder}`.trim();
        if (isSubstantiveAnswerText(combinedAnswer)) {
          const draft = draftsRef.current[question.id];
          if (draft && answerRemainder) {
            const now = Date.now();
            if (draft.lastSpeechAt && now - draft.lastSpeechAt > 5000) draft.longPauseCount += 1;
            draft.lastSpeechAt = now;
            draft.confidenceSamples.push(confidence);
            draft.words += wordCount(answerRemainder);
          }
          if (answerRemainder) {
            setAnswers((current) => ({
              ...current,
              [question.id]: combinedAnswer,
            }));
          }
          void recordRuntimeCommand("answer_then_next", question, { source: "speech" });
          await speakBot("Got it. I will submit the answer you gave and move to the next question.", question.id);
          await submitQuestionRef.current(question, currentIndexRef.current, {
            answer: combinedAnswer,
            answerSource: "spoken_next_request",
          });
          return;
        }

        void recordRuntimeCommand("pass", question, { source: "speech" });
        await speakBot("Understood. I will mark this question as passed and move to the next one.", question.id);
        await submitQuestionRef.current(question, currentIndexRef.current, {
          answer: "",
          answerSource: "pass",
        });
        return;
      }

      const draft = draftsRef.current[question.id];
      if (draft) {
        const now = Date.now();
        if (draft.lastSpeechAt && now - draft.lastSpeechAt > 5000) draft.longPauseCount += 1;
        draft.lastSpeechAt = now;
        draft.confidenceSamples.push(confidence);
        draft.words += wordCount(cleanText);
      }
      setAnswers((current) => ({
        ...current,
        [question.id]: `${current[question.id] || ""}${current[question.id] ? " " : ""}${cleanText}`,
      }));
    },
    [addLine, analyzeRealtimeSpeech, recordRuntimeCommand, recordUnclearSpeech, questions, setListenMode, speakBot]
  );

  const handlePartialSpeech = useCallback(
    (text: string) => {
      const question = questions[currentIndexRef.current];
      if (question && answerModeFor(round, question, currentIndexRef.current) === "code") {
        setPartialTranscript("");
        return;
      }
      setPartialTranscript(text);
      analyzeRealtimeSpeech(text, "partial");
    },
    [analyzeRealtimeSpeech, questions, round]
  );

  const media = useRealtimeInterviewSession({
    interviewId,
    round,
    previewActive: phase === "lobby",
    callActive: phase === "active",
    captureMode: listenMode,
    botSpeaking,
    language: voiceProfile.lang,
    onFinalTranscript: handleFinalSpeech,
    onPartialTranscript: handlePartialSpeech,
    onMediaEvent: handleMediaEvent,
  });
  const stopRoundCallMedia = media.stopCallMedia;
  const stopRoundPreview = media.stopPreview;

  const mediaStateRef = useRef({ cameraEnabled: media.cameraEnabled, micEnabled: media.micEnabled });
  useEffect(() => {
    mediaStateRef.current = { cameraEnabled: media.cameraEnabled, micEnabled: media.micEnabled };
  }, [media.cameraEnabled, media.micEnabled]);

  useEffect(() => {
    if (!allSubmitted || phaseRef.current !== "lobby") return;
    cancelBotSpeech();
    setListenMode("idle");
    setTimerEndsAt(null);
    setCodeDialogOpen(false);
    setEndCallConfirmMode(null);
    fullscreenBlockRef.current = null;
    setFullscreenBlock(null);
    void stopRoundCallMedia().catch(() => undefined);
    stopRoundPreview();
    setPhaseSynced("evaluation");
  }, [allSubmitted, cancelBotSpeech, setListenMode, setPhaseSynced, stopRoundCallMedia, stopRoundPreview]);

  const answersRef = useRef(answers);
  useEffect(() => {
    answersRef.current = answers;
  }, [answers]);

  const fetchParaphraseRef = useRef<(question: InterviewQuestion) => Promise<string>>(async () => "");
  const submitQuestionRef = useRef<
    (
      question: InterviewQuestion,
      index: number,
      options: { answer?: string; answerSource: string; timerExpired?: boolean; moveNext?: boolean }
    ) => Promise<void>
  >(async () => undefined);

  useEffect(() => {
    if (previewVideoRef.current) {
      previewVideoRef.current.srcObject = media.previewStream;
      previewVideoRef.current.play().catch(() => undefined);
    }
  }, [media.previewStream, phase]);

  useEffect(() => {
    if (phase !== "active" || !videoRef.current) return;
    videoRef.current.srcObject = media.activeStream;
    videoRef.current.play().catch(() => undefined);
  }, [media.activeStream, media.cameraDeviceReady, media.cameraEnabled, phase]);

  const currentTranscript = useMemo(() => transcript, [transcript]);
  const roundProctorEvents = useMemo(
    () => proctorEvents.filter((event) => event.severity === "warning" || event.severity === "critical"),
    [proctorEvents]
  );

  useEffect(() => {
    transcriptScrollRef.current?.scrollTo({
      top: transcriptScrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [partialTranscript, transcript]);

  const fetchParaphrase = useCallback(
    async (question: InterviewQuestion) => {
      try {
        const response = await apiService.request<{ paraphrase: string }>(`/api/${round}/paraphrase`, {
          method: "POST",
          body: {
            interview_id: interviewId,
            question_id: question.id,
            question_text: questionText(question),
          },
        });
        return cleanGeneratedText(response.paraphrase, fallbackParaphrase(questionText(question)));
      } catch {
        return fallbackParaphrase(questionText(question));
      }
    },
    [interviewId, round]
  );

  useEffect(() => {
    fetchParaphraseRef.current = fetchParaphrase;
  }, [fetchParaphrase]);

  const submitQuestion = useCallback(
    async (
      question: InterviewQuestion,
      index: number,
      options: {
        answer?: string;
        answerSource: string;
        timerExpired?: boolean;
        moveNext?: boolean;
      }
    ) => {
      if (!interviewId || submittingRef.current[question.id]) return;
      submittingRef.current[question.id] = true;
      setIsSubmitting(true);
      setLastError("");
      cancelBotSpeech();
      setListenMode("idle");
      setTimerEndsAt(null);
      setCodeDialogOpen(false);

      const answerMode = answerModeFor(round, question, index);
      const answer = options.answer ?? (answerMode === "code" ? codeAnswers[question.id] || "" : answers[question.id] || "");
      const startedAt = questionStartedRef.current[question.id] || Date.now();
      const metrics = answerMode === "code" ? codeAnswerMetrics(answer, startedAt) : buildMetrics(draftsRef.current[question.id], answer, startedAt);
      const questionEvents = proctorEvents.filter((event) => event.questionId === question.id);
      const timeTakenSeconds = Math.max(1, Math.round((Date.now() - startedAt) / 1000));
      setMetricsByQuestion((current) => ({ ...current, [question.id]: metrics }));

      try {
        const response = await apiService.request<AnswerRoundResult & { runtime?: RoundRuntimeResponse }>(endpoint, {
          method: "POST",
          body: {
            interview_id: interviewId,
            question_id: question.id,
            answer,
            transcript_confidence: answerMode === "code" ? null : metrics.averageConfidence,
            answer_mode: answerMode,
            time_taken_seconds: timeTakenSeconds,
            timer_expired: Boolean(options.timerExpired),
            speech_metrics: metrics,
            proctor_events: questionEvents,
            repeat_count: repeatCountsRef.current[question.id] || 0,
            paraphrase_count: paraphraseCountsRef.current[question.id] || 0,
            answer_source: options.answerSource,
          },
        });

        const backendRuntime = response.runtime;
        const normalizedResponse: AnswerRoundResult = {
          ...response,
          answerMode,
          timeTakenSeconds,
          timerExpired: Boolean(options.timerExpired),
          speechMetrics: metrics,
          proctorEvents: questionEvents,
          repeatCount: repeatCountsRef.current[question.id] || 0,
          paraphraseCount: paraphraseCountsRef.current[question.id] || 0,
          answerSource: options.answerSource,
        };

        setAnswerRoundResult(round, question.id, normalizedResponse);
        void refreshWorkflowState();
        const backendNextIndex = applyRuntimeState(backendRuntime);
        addTranscriptEntry(
          {
            id: question.id,
            timestamp: new Date(),
            speaker: "user",
            text: answer || options.answerSource,
            confidence: metrics.averageConfidence,
          },
          round
        );
        addExecutionLog({
          type: normalizedResponse.score >= 70 ? "success" : "warning",
          agent: agentName,
          message: `Question ${askedQuestionSequenceRef.current[question.id] || index + 1} scored ${Math.round(normalizedResponse.score)}/100.`,
        });

        const callStillActive = phaseRef.current === "active" && !finishingRef.current;
        if (backendRuntime?.runtime.status === "awaiting_follow_up" && backendRuntime.followUpPrompt && callStillActive) {
          submittingRef.current[question.id] = false;
          const timerSeconds = backendRuntime.runtime.timer.timerSeconds || timerSecondsFor(round, question, index);
          setTimerEndsAt(Date.now() + timerSeconds * 1000);
          await speakBot(backendRuntime.followUpPrompt, question.id);
          if (phaseRef.current === "active" && !fullscreenBlockRef.current) {
            if (answerMode === "code") setCodeDialogOpen(true);
            else setListenMode("answer");
          }
          return;
        }

        if (options.moveNext !== false && callStillActive) {
          const nextIndex =
            backendRuntime && backendRuntime.runtime.status !== "completed" && backendNextIndex >= 0
              ? backendNextIndex
              : index + 1;
          if (backendRuntime?.runtime.status !== "completed" && nextIndex < questions.length) {
            window.setTimeout(() => void askQuestionRef.current(nextIndex), 700);
          } else {
            finishingRef.current = true;
            setTimerEndsAt(null);
            setCodeDialogOpen(false);
            setPhaseSynced("evaluation");
            void media.stopCallMedia().catch(() => undefined);
            addExecutionLog({
              type: "success",
              agent: profile.accent,
              message: `${title} completed. Review the evaluation panel before continuing.`,
            });
          }
        }
      } catch (error) {
        submittingRef.current[question.id] = false;
        setLastError(error instanceof Error ? error.message : `Unable to score ${round} answer.`);
        addExecutionLog({
          type: "error",
          agent: agentName,
          message: error instanceof Error ? error.message : `Unable to score ${round} answer.`,
        });
      } finally {
        setIsSubmitting(false);
      }
    },
    [
      addExecutionLog,
      addTranscriptEntry,
      agentName,
      answers,
      applyRuntimeState,
      cancelBotSpeech,
      codeAnswers,
      endpoint,
      interviewId,
      media,
      profile.accent,
      proctorEvents,
      questions.length,
      refreshWorkflowState,
      round,
      setAnswerRoundResult,
      setListenMode,
      setPhaseSynced,
      speakBot,
      title,
    ]
  );

  useEffect(() => {
    submitQuestionRef.current = submitQuestion;
  }, [submitQuestion]);

  const askQuestion = useCallback(
    async (index: number) => {
      const question = questions[index];
      if (!question || phaseRef.current !== "active" || fullscreenBlockRef.current) return;
      setListenMode("idle");
      setCodeDialogOpen(false);
      setCurrentIndexSynced(index);
      const mode = answerModeFor(round, question, index);
      const timerSeconds = runtimeTimerSecondsRef.current[question.id] || timerSecondsFor(round, question, index);
      if (!askedQuestionSequenceRef.current[question.id]) {
        askedQuestionSequenceRef.current[question.id] = nextAskedQuestionNumberRef.current;
        nextAskedQuestionNumberRef.current += 1;
      }
      const askedNumber = askedQuestionSequenceRef.current[question.id];
      questionStartedRef.current[question.id] = Date.now();
      draftsRef.current[question.id] = {
        startedAt: Date.now(),
        lastSpeechAt: null,
        confidenceSamples: [],
        words: 0,
        longPauseCount: 0,
        unclearCount: 0,
        realtimeSignals: [],
      };
      setTimerEndsAt(Date.now() + timerSeconds * 1000);

      const intro =
        mode === "code"
          ? `Question ${askedNumber}. This one needs a written code answer. ${questionText(question)} I am opening the editor now. You have ten minutes. If you finish before time, press Submit Code.`
          : `Question ${askedNumber}. ${questionText(question)} You have ${Math.round(timerSeconds / 60)} minutes. If you finish before time, press Submit Answer.`;

      await speakBot(intro, question.id, mode === "spoken" ? "answer" : undefined);
      if (phaseRef.current !== "active" || fullscreenBlockRef.current || currentIndexRef.current !== index || submittingRef.current[question.id]) {
        return;
      }
      if (mode === "code") setCodeDialogOpen(true);
      else setListenMode("answer");
    },
    [questions, round, setCurrentIndexSynced, setListenMode, speakBot]
  );

  useEffect(() => {
    askQuestionRef.current = askQuestion;
  }, [askQuestion]);

  useEffect(() => {
    if (!timerEndsAt || phase !== "active" || !selectedQuestion || fullscreenBlock) return;
    const interval = window.setInterval(() => {
      const remaining = Math.max(0, Math.ceil((timerEndsAt - Date.now()) / 1000));
      setRemainingSeconds(remaining);
      if (remaining <= 0) {
        window.clearInterval(interval);
        const question = questions[currentIndexRef.current];
        if (question && !submittingRef.current[question.id]) {
          void submitQuestion(question, currentIndexRef.current, {
            answer:
              answerModeFor(round, question, currentIndexRef.current) === "code"
                ? codeAnswers[question.id] || ""
                : answers[question.id] || "",
            answerSource: "timer_expired",
            timerExpired: true,
          });
        }
      }
    }, 250);
    return () => window.clearInterval(interval);
  }, [answers, codeAnswers, fullscreenBlock, phase, questions, round, selectedQuestion, submitQuestion, timerEndsAt]);

  useEffect(() => {
    if (phase !== "active") return;
    const handleVisibility = () => {
      if (document.visibilityState === "hidden") {
        registerProctorEvent("visibility", "Interview tab was hidden or switched.");
      }
    };
    const handleBlur = () => registerProctorEvent("focus", "Interview window lost focus.");
    const handlePointerLeave = (event: MouseEvent) => {
      const related = event.relatedTarget as Node | null;
      if (related && document.documentElement.contains(related)) return;
      if (pointerLeaveTimerRef.current) window.clearTimeout(pointerLeaveTimerRef.current);
      pointerLeaveTimerRef.current = window.setTimeout(() => {
        registerProctorEvent("cursor", "Cursor left the interview screen for more than 3 seconds.");
      }, 3000);
    };
    const handlePointerEnter = () => {
      if (pointerLeaveTimerRef.current) window.clearTimeout(pointerLeaveTimerRef.current);
    };

    document.addEventListener("visibilitychange", handleVisibility);
    window.addEventListener("blur", handleBlur);
    document.documentElement.addEventListener("mouseout", handlePointerLeave);
    document.documentElement.addEventListener("mouseover", handlePointerEnter);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibility);
      window.removeEventListener("blur", handleBlur);
      document.documentElement.removeEventListener("mouseout", handlePointerLeave);
      document.documentElement.removeEventListener("mouseover", handlePointerEnter);
      if (pointerLeaveTimerRef.current) window.clearTimeout(pointerLeaveTimerRef.current);
    };
  }, [phase, registerProctorEvent]);

  useEffect(() => {
    if (phase !== "active" || !media.activeStream) return;
    let cancelled = false;
    let interval: number | null = null;

    async function startObjectDetection() {
      try {
        await import("@tensorflow/tfjs");
        const coco = await import("@tensorflow-models/coco-ssd");
        const model = await coco.load({ base: "lite_mobilenet_v2" as any });
        objectDetectionStreakRef.current = { phone: 0, multiplePeople: 0 };
        if (cancelled) return;
        interval = window.setInterval(async () => {
          const video = videoRef.current;
          if (!media.cameraEnabled || !media.cameraDeviceReady || !video || video.readyState < 2 || phaseRef.current !== "active") return;
          try {
            const predictions = await model.detect(video);
            const phone = predictions.find((prediction) => prediction.class === "cell phone" && prediction.score > 0.7);
            const people = predictions.filter((prediction) => prediction.class === "person" && prediction.score > 0.72);
            objectDetectionStreakRef.current.phone = phone ? objectDetectionStreakRef.current.phone + 1 : 0;
            objectDetectionStreakRef.current.multiplePeople =
              people.length > 1 ? objectDetectionStreakRef.current.multiplePeople + 1 : 0;
            if (objectDetectionStreakRef.current.phone >= 2) registerProctorEvent("object", "Phone detected in the camera frame.");
            if (objectDetectionStreakRef.current.multiplePeople >= 3) {
              registerProctorEvent("object", "Multiple people detected in the camera frame.");
            }
          } catch {
            // A single warmup frame can fail without affecting the proctor loop.
          }
        }, 3000);
      } catch {
        addExecutionLog({
          type: "warning",
          agent: "AI Proctor",
          message: "Object detection model could not load; tab, fullscreen, media, and face checks remain active.",
        });
      }
    }

    void startObjectDetection();
    return () => {
      cancelled = true;
      if (interval) window.clearInterval(interval);
    };
  }, [addExecutionLog, media.activeStream, media.cameraDeviceReady, media.cameraEnabled, phase, registerProctorEvent]);

  useEffect(() => {
    if (phase !== "active" || !media.activeStream) return;
    let cancelled = false;
    let interval: number | null = null;

    faceDetectionStreakRef.current = { none: 0, multiple: 0 };

    const reportFaces = (count: number) => {
      if (count === 0) {
        faceDetectionStreakRef.current.none += 1;
        faceDetectionStreakRef.current.multiple = 0;
      } else if (count > 1) {
        faceDetectionStreakRef.current.multiple += 1;
        faceDetectionStreakRef.current.none = 0;
      } else {
        faceDetectionStreakRef.current = { none: 0, multiple: 0 };
      }
      if (faceDetectionStreakRef.current.none >= 3) registerProctorEvent("face", "No face detected in the camera frame.");
      if (faceDetectionStreakRef.current.multiple >= 4) {
        registerProctorEvent("face", "Multiple faces detected in the camera frame.");
      }
    };

    async function startFaceDetection() {
      const FaceDetectorCtor = (window as typeof window & { FaceDetector?: any }).FaceDetector;
      if (FaceDetectorCtor) {
        try {
          const detector = new FaceDetectorCtor({ fastMode: true, maxDetectedFaces: 3 });
          interval = window.setInterval(async () => {
            const video = videoRef.current;
            if (!media.cameraEnabled || !media.cameraDeviceReady || !video || video.readyState < 2 || fullscreenBlockRef.current) return;
            try {
              const faces = await detector.detect(video);
              reportFaces(faces.length);
            } catch {
              // Native detector can throw while video is warming up.
            }
          }, 2500);
          return;
        } catch {
          // Fall through to BlazeFace.
        }
      }

      try {
        await import("@tensorflow/tfjs");
        const blazeface = await import("@tensorflow-models/blazeface");
        const model = await blazeface.load();
        if (cancelled) return;
        interval = window.setInterval(async () => {
          const video = videoRef.current;
          if (!media.cameraEnabled || !media.cameraDeviceReady || !video || video.readyState < 2 || fullscreenBlockRef.current) return;
          try {
            const faces = await model.estimateFaces(video, false);
            reportFaces(faces.length);
          } catch {
            // Detection can miss a transient frame.
          }
        }, 2500);
      } catch {
        addExecutionLog({
          type: "warning",
          agent: "AI Proctor",
          message: "Face detection model could not load; tab, fullscreen, media, and object checks remain active.",
        });
      }
    }

    void startFaceDetection();
    return () => {
      cancelled = true;
      if (interval) window.clearInterval(interval);
    };
  }, [addExecutionLog, media.activeStream, media.cameraDeviceReady, media.cameraEnabled, phase, registerProctorEvent]);

  const restoreFullscreen = useCallback(async () => {
    if (!callRootRef.current?.requestFullscreen) {
      fullscreenBlockRef.current = null;
      setFullscreenBlock(null);
      return;
    }
    try {
      await callRootRef.current.requestFullscreen();
      fullscreenBlockRef.current = null;
      setFullscreenBlock(null);
      addLine({ speaker: "system", text: "Fullscreen restored. Continue the interview." });
      const pausedSeconds = pausedRemainingSecondsRef.current;
      pausedRemainingSecondsRef.current = null;
      if (pausedSeconds && selectedQuestion) setTimerEndsAt(Date.now() + pausedSeconds * 1000);
      if (selectedMode === "code" && pausedCodeDialogOpenRef.current) {
        setCodeDialogOpen(true);
      } else if (pausedListenModeRef.current !== "idle" && !botSpeakingRef.current) {
        setListenMode(pausedListenModeRef.current);
      }
      pausedCodeDialogOpenRef.current = false;
    } catch {
      const block = {
        mode: "recover",
        message: "Fullscreen permission was not granted. Click Re-enter Fullscreen to continue this round.",
      } satisfies NonNullable<FullscreenBlock>;
      fullscreenBlockRef.current = block;
      setFullscreenBlock(block);
    }
  }, [addLine, selectedMode, selectedQuestion, setListenMode]);

  const startInterview = async () => {
    if (!interviewId || questions.length === 0) return;
    setIsStarting(true);
    setLastError("");
    finishingRef.current = false;
    violationCountRef.current = 0;
    lastViolationAtRef.current = {};
    objectDetectionStreakRef.current = { phone: 0, multiplePeople: 0 };
    faceDetectionStreakRef.current = { none: 0, multiple: 0 };
    pausedRemainingSecondsRef.current = null;
    pausedCodeDialogOpenRef.current = false;
    askedQuestionSequenceRef.current = {};
    nextAskedQuestionNumberRef.current = 1;
    lastRealtimeSignalAtRef.current = {};
    fullscreenBlockRef.current = null;
    setFullscreenBlock(null);

    try {
      const runtimeStatePromise = apiService.request<RoundRuntimeResponse>(
        `/api/${round}/interviews/${interviewId}/runtime/start`,
        { method: "POST" }
      );
      if (typeof document !== "undefined" && !document.fullscreenElement && document.documentElement.requestFullscreen) {
        await document.documentElement.requestFullscreen().catch(() => {
          addExecutionLog({ type: "warning", agent: "AI Proctor", message: "Fullscreen permission was not granted." });
        });
      }
      const mediaPromise = media.startCallMedia();
      const runtimeState = await runtimeStatePromise;
      applyRuntimeState(runtimeState);
      await mediaPromise;
      setPhaseSynced("active");

      const intro =
        round === "hr"
          ? `Hi, my name is ${profile.name}. I am your HR interviewer, and I will be taking your interview today. I will evaluate every answer with the same neutral rubric. Can we start?`
          : `Hi, my name is ${profile.name}. I am your technical interviewer, and I will be taking your interview today. I will evaluate only your answer quality, reasoning, communication clarity, and observed proctoring signals. Can we start?`;
      await speakBot(intro);
      setListenMode("consent");
    } catch (error) {
      setLastError(error instanceof Error ? error.message : "Unable to start realtime interview media.");
      await media.stopCallMedia();
      setPhaseSynced("lobby");
    } finally {
      setIsStarting(false);
    }
  };

  const submitSpokenNow = () => {
    if (!selectedQuestion || selectedMode !== "spoken" || fullscreenBlockRef.current) return;
    if (!(answers[selectedQuestion.id] || "").trim()) {
      setLastError("No spoken answer has been captured yet. Unmute the microphone and answer out loud, or pass the question.");
      if (media.micEnabled && media.micDeviceReady) setListenMode("answer");
      return;
    }
    void submitQuestion(selectedQuestion, currentIndex, {
      answer: answers[selectedQuestion.id] || "",
      answerSource: "spoken_submit",
    });
  };

  const repeatQuestionNow = () => {
    if (!selectedQuestion || fullscreenBlockRef.current) return;
    repeatCountsRef.current[selectedQuestion.id] = (repeatCountsRef.current[selectedQuestion.id] || 0) + 1;
    void recordRuntimeCommand("repeat", selectedQuestion, { source: "button" });
    void speakBot(`Sure. ${questionText(selectedQuestion)}`, selectedQuestion.id).then(() => {
      if (phaseRef.current === "active" && !fullscreenBlockRef.current && media.micEnabled && selectedMode === "spoken") {
        setListenMode("answer");
      }
    });
  };

  const paraphraseQuestionNow = async () => {
    if (!selectedQuestion || fullscreenBlockRef.current) return;
    paraphraseCountsRef.current[selectedQuestion.id] = (paraphraseCountsRef.current[selectedQuestion.id] || 0) + 1;
    void recordRuntimeCommand("paraphrase", selectedQuestion, { source: "button" });
    const paraphrase = await fetchParaphrase(selectedQuestion);
    await speakBot(paraphrase, selectedQuestion.id);
    if (phaseRef.current === "active" && !fullscreenBlockRef.current && media.micEnabled && selectedMode === "spoken") {
      setListenMode("answer");
    }
  };

  const toggleMic = async () => {
    if (fullscreenBlockRef.current) return;
    const next = !media.micEnabled;
    if (!next) {
      pausedListenModeRef.current = listenModeRef.current;
      setListenMode("idle");
    }
    await media.setMicEnabled(next);
    addLine({ speaker: "system", text: next ? "Microphone unmuted." : "Microphone muted." });
    if (next && phaseRef.current === "active" && !botSpeakingRef.current && selectedMode === "spoken") {
      setListenMode(pausedListenModeRef.current !== "idle" ? pausedListenModeRef.current : "answer");
    }
  };

  const toggleCamera = async () => {
    if (fullscreenBlockRef.current) return;
    const next = !media.cameraEnabled;
    await media.setCameraEnabled(next);
    addLine({ speaker: "system", text: next ? "Camera turned on." : "Camera turned off." });
  };

  const endCallNow = async (confirmedMode?: EndCallConfirmMode) => {
    if (finishingRef.current && phaseRef.current !== "active") return;
    if (fullscreenBlockRef.current?.mode === "end") {
      if (confirmedMode !== "locked") {
        setEndCallConfirmMode("locked");
        return;
      }
      const message = fullscreenBlockRef.current.message;
      finishingRef.current = true;
      cancelBotSpeech();
      setListenMode("idle");
      setTimerEndsAt(null);
      setCodeDialogOpen(false);
      fullscreenBlockRef.current = null;
      setFullscreenBlock(null);
      setTerminationMessage(message);
      setPhaseSynced("terminated");
      void media.stopCallMedia().catch(() => undefined);
      addExecutionLog({ type: "error", agent: "AI Proctor", message });
      return;
    }
    if (confirmedMode !== "manual") {
      setEndCallConfirmMode("manual");
      return;
    }

    finishingRef.current = true;
    cancelBotSpeech();
    setListenMode("idle");
    setTimerEndsAt(null);
    setCodeDialogOpen(false);
    addLine({ speaker: "system", text: "Call ended by candidate." });
    void recordRuntimeCommand("end_round", selectedQuestion, { source: "end_call_button" });

    try {
      setPhaseSynced("evaluation");
      void media.stopCallMedia().catch(() => undefined);
      const unanswered = questions
        .map((question, index) => {
          const answerMode = answerModeFor(round, question, index);
          const answer = answerMode === "code" ? codeAnswers[question.id] || "" : answers[question.id] || "";
          const startedAt = questionStartedRef.current[question.id] || Date.now();
          const metrics = answerMode === "code" ? codeAnswerMetrics(answer, startedAt) : buildMetrics(draftsRef.current[question.id], answer, startedAt);
          const questionEvents = proctorEvents.filter((event) => event.questionId === question.id);
          const timeTakenSeconds = Math.max(1, Math.round((Date.now() - startedAt) / 1000));
          return { question, index, answerMode, answer, metrics, questionEvents, timeTakenSeconds };
        })
        .filter(({ question }) => !results[question.id]);

      if (unanswered.length > 0) {
        setMetricsByQuestion((current) => ({
          ...current,
          ...Object.fromEntries(unanswered.map(({ question, metrics }) => [question.id, metrics])),
        }));
      }

      unanswered.forEach(({ question, index, answerMode, answer, metrics, questionEvents, timeTakenSeconds }) => {
        setAnswerRoundResult(round, question.id, {
          id: nowId(`${round}-end-call`),
          score: 0,
          feedback: answer.trim()
            ? "The call was ended before this answer could be scored. The backend will update this result when saving finishes."
            : "No answer was submitted for this question.",
          matchedKeywords: [],
          answerMode,
          timeTakenSeconds,
          timerExpired: false,
          speechMetrics: metrics,
          proctorEvents: questionEvents,
          repeatCount: repeatCountsRef.current[question.id] || 0,
          paraphraseCount: paraphraseCountsRef.current[question.id] || 0,
          answerSource: "end_call",
        });

        if (submittingRef.current[question.id]) return;
        submittingRef.current[question.id] = true;
        void apiService
          .request<AnswerRoundResult & { runtime?: RoundRuntimeResponse }>(endpoint, {
            method: "POST",
            body: {
              interview_id: interviewId,
              question_id: question.id,
              answer,
              transcript_confidence: answerMode === "code" ? null : metrics.averageConfidence,
              answer_mode: answerMode,
              time_taken_seconds: timeTakenSeconds,
              timer_expired: false,
              speech_metrics: metrics,
              proctor_events: questionEvents,
              repeat_count: repeatCountsRef.current[question.id] || 0,
              paraphrase_count: paraphraseCountsRef.current[question.id] || 0,
              answer_source: "end_call",
            },
          })
          .then((response) => {
            setAnswerRoundResult(round, question.id, {
              ...response,
              answerMode,
              timeTakenSeconds,
              timerExpired: false,
              speechMetrics: metrics,
              proctorEvents: questionEvents,
              repeatCount: repeatCountsRef.current[question.id] || 0,
              paraphraseCount: paraphraseCountsRef.current[question.id] || 0,
              answerSource: "end_call",
            });
          })
          .catch((error) => {
            addExecutionLog({
              type: "warning",
              agent: profile.accent,
              message: error instanceof Error ? error.message : `Unable to save skipped question ${index + 1}.`,
            });
          })
          .finally(() => {
            submittingRef.current[question.id] = false;
            void refreshWorkflowState();
          });
      });

      addExecutionLog({
        type: "warning",
        agent: profile.accent,
        message: `${title} call ended manually. Evaluation was generated from captured and unanswered responses.`,
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  const restartSameRound = () => {
    finishingRef.current = false;
    violationCountRef.current = 0;
    submittingRef.current = {};
    draftsRef.current = {};
    repeatCountsRef.current = {};
    paraphraseCountsRef.current = {};
    questionStartedRef.current = {};
    lastViolationAtRef.current = {};
    objectDetectionStreakRef.current = { phone: 0, multiplePeople: 0 };
    faceDetectionStreakRef.current = { none: 0, multiple: 0 };
    pausedRemainingSecondsRef.current = null;
    pausedCodeDialogOpenRef.current = false;
    pausedListenModeRef.current = "idle";
    runtimeStartIndexRef.current = 0;
    runtimeTimerSecondsRef.current = {};
    askedQuestionSequenceRef.current = {};
    nextAskedQuestionNumberRef.current = 1;
    lastRealtimeSignalAtRef.current = {};
    cancelBotSpeech();
    void media.stopCallMedia();
    clearAnswerRound(round);
    if (interviewId) {
      clearAutosavedValue(interviewId, `${round}-spoken-answers`);
      clearAutosavedValue(interviewId, `${round}-code-answers`);
      void apiService.request(`/api/${round}/interviews/${interviewId}/answers`, { method: "DELETE" }).catch((error) => {
        addExecutionLog({
          type: "warning",
          agent: profile.accent,
          message: error instanceof Error ? error.message : "Unable to clear backend round answers.",
        });
      });
    }
    setPhaseSynced("lobby");
    setInterviewSessionStatus("active");
    setNavigationLocked(true);
    setCurrentIndexSynced(0);
    setListenMode("idle");
    setTimerEndsAt(null);
    setRemainingSeconds(0);
    setTranscript([]);
    setAnswers({});
    setCodeAnswers({});
    setMetricsByQuestion({});
    setProctorEvents([]);
    fullscreenBlockRef.current = null;
    setFullscreenBlock(null);
    setWarningMessage("");
    setClearSpeechMessage("");
    setTerminationMessage("");
    setLastError("");
    setCodeDialogOpen(false);
    setIsSubmitting(false);
  };

  const submitCodeNow = (source: "code_submit" | "dont_know") => {
    if (!selectedQuestion || selectedMode !== "code" || fullscreenBlockRef.current) return;
    setCodeDialogOpen(false);
    void submitQuestion(selectedQuestion, currentIndex, {
      answer: source === "dont_know" ? "" : codeAnswers[selectedQuestion.id] || "",
      answerSource: source,
    });
  };

  const completeRound = async () => {
    if (!allSubmitted || completionDisabled) return;
    setIsCompleting(true);
    try {
      await onComplete();
    } finally {
      setIsCompleting(false);
    }
  };

  const micBadgeText = !media.micEnabled
    ? "Mic muted"
    : phase === "active" && !media.micDeviceReady
    ? "Mic reconnecting"
    : media.isListening
    ? media.userSpeaking
      ? "Speaking"
      : "Listening"
    : media.micSignalPaused
    ? "Mic signal paused"
    : media.speechStatus;
  const realtimeBadgeText = media.liveKitConnected
    ? "LiveKit audio"
    : media.liveKitEnabled
    ? "LiveKit reconnecting"
    : "Local audio";
  const transcriptionStandby = phase === "active" && (botSpeaking || selectedMode === "code" || listenMode === "idle");
  const transcriptionBadgeText =
    selectedMode === "code" && phase === "active"
      ? "STT off for code"
      : transcriptionStandby
      ? "Deepgram standby"
      : media.transcriptionMode === "deepgram"
      ? media.transcriptionConnected
        ? "Deepgram STT"
        : "STT connecting"
      : media.transcriptionMode === "browser-fallback"
      ? "Browser STT fallback"
      : "STT unavailable";

  if (!interviewId || questions.length === 0) {
    return (
      <Card className="border-hairline bg-surface-1">
        <CardContent className="py-16 text-center">
          <Bot className="mx-auto mb-4 h-10 w-10 text-ink-muted" />
          <h3 className="mb-2 text-headline text-ink">Start an interview first</h3>
          <p className="mx-auto mb-6 max-w-xl text-body text-ink-muted">{emptyMessage}</p>
          <Button onClick={() => setCurrentStep("form")} className="rounded-pill bg-primary text-on-primary">
            Go to Form
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <div ref={callRootRef} className={cn("min-h-0", phase === "active" && "fixed inset-0 z-50 bg-black")}>
      <InterviewLiveKitAudioLayer
        room={media.liveKitRoom}
        serverUrl={media.liveKitServerUrl}
        token={media.liveKitToken}
        connected={media.liveKitConnected}
      />

      {phase === "lobby" && (
        <Card className="border-hairline bg-surface-1">
          <CardHeader>
            <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
              <div>
                <CardTitle className="text-headline text-ink">{title}</CardTitle>
                <p className="mt-1 max-w-3xl text-body-sm text-ink-muted">{description}</p>
              </div>
              <Badge variant="outline" className="w-fit border-hairline text-ink-muted">
                {round === "technical" ? "3 spoken + 2 code" : "Spoken HR call"}
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
            <div className="rounded-lg border border-hairline bg-surface-2 p-6">
              <div className="flex flex-col gap-6 lg:flex-row lg:items-center">
                <div className="flex min-w-0 flex-1 items-center gap-4">
                  <div className="relative h-28 w-28 shrink-0 overflow-hidden rounded-full border border-semantic-success/70 bg-black/30">
                    <Image
                      src={profile.asset}
                      alt=""
                      fill
                      sizes="112px"
                      className="h-full w-full object-cover object-top"
                      style={{
                        filter:
                          "drop-shadow(2px 0 #22c55e) drop-shadow(-2px 0 #22c55e) drop-shadow(0 2px #22c55e) drop-shadow(0 -2px #22c55e)",
                      }}
                    />
                  </div>
                  <div className="min-w-0">
                    <p className="text-caption uppercase text-ink-muted">{profile.accent}</p>
                    <h3 className="mt-1 text-display-md text-ink">{profile.name}</h3>
                    <p className="mt-2 max-w-2xl text-body text-ink-muted">
                      Your bot interviewer controls the call, timers, transcript, proctor checks, and unbiased scoring handoff.
                      Questions stay hidden until the call begins.
                    </p>
                  </div>
                </div>
                <Button
                  type="button"
                  onClick={startInterview}
                  disabled={isStarting}
                  className="h-11 rounded-md bg-primary px-5 text-on-primary"
                >
                  {isStarting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
                  {isStarting ? "Starting..." : "Start Interview Call"}
                </Button>
              </div>

              <div className="mt-6 grid grid-cols-1 gap-3 md:grid-cols-3">
                <div className="rounded-md border border-hairline bg-surface-1 p-4">
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <span className="flex items-center gap-2 text-body-sm text-ink">
                      {media.cameraEnabled ? <Camera className="h-4 w-4 text-semantic-success" /> : <CameraOff className="h-4 w-4" />}
                      Camera
                    </span>
                    <Switch aria-label="Toggle camera" checked={media.cameraEnabled} onCheckedChange={(checked) => void media.setCameraEnabled(checked)} />
                  </div>
                  <p className="text-caption text-ink-muted">
                    {media.cameraEnabled ? (media.cameraDeviceReady ? "Preview connected." : "Waiting for camera.") : "Camera off."}
                  </p>
                  {media.videoInputs.length > 1 && (
                    <select
                      aria-label="Camera device"
                      value={media.selectedVideoDeviceId || ""}
                      onChange={(event) => void media.selectVideoInput(event.target.value)}
                      className="mt-3 h-9 w-full rounded-md border border-hairline bg-surface-2 px-2 text-caption text-ink"
                    >
                      <option value="">Default camera</option>
                      {media.videoInputs.map((device, index) => (
                        <option key={device.deviceId || `video-${index}`} value={device.deviceId}>
                          {device.label || `Camera ${index + 1}`}
                        </option>
                      ))}
                    </select>
                  )}
                </div>
                <div className="rounded-md border border-hairline bg-surface-1 p-4">
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <span className="flex items-center gap-2 text-body-sm text-ink">
                      {media.micEnabled ? <Mic className="h-4 w-4 text-semantic-success" /> : <MicOff className="h-4 w-4" />}
                      Microphone
                    </span>
                    <Switch aria-label="Toggle microphone" checked={media.micEnabled} onCheckedChange={(checked) => void media.setMicEnabled(checked)} />
                  </div>
                  <p className="text-caption text-ink-muted">
                    {media.micEnabled ? (media.micDeviceReady ? "Input connected." : "Waiting for microphone.") : "Microphone muted."}
                  </p>
                  {media.audioInputs.length > 1 && (
                    <select
                      aria-label="Microphone device"
                      value={media.selectedAudioDeviceId || ""}
                      onChange={(event) => void media.selectAudioInput(event.target.value)}
                      className="mt-3 h-9 w-full rounded-md border border-hairline bg-surface-2 px-2 text-caption text-ink"
                    >
                      <option value="">Default microphone</option>
                      {media.audioInputs.map((device, index) => (
                        <option key={device.deviceId || `audio-${index}`} value={device.deviceId}>
                          {device.label || `Microphone ${index + 1}`}
                        </option>
                      ))}
                    </select>
                  )}
                </div>
                <div className="rounded-md border border-hairline bg-surface-1 p-4">
                  <div className="mb-3 flex items-center gap-2 text-body-sm text-ink">
                    <ShieldCheck className="h-4 w-4 text-semantic-success" />
                    Integrity
                  </div>
                  <p className="text-caption text-ink-muted">Fullscreen, focus, face, object, and media events are logged to backend runtime.</p>
                </div>
              </div>

              {(media.mediaError || media.speechError || lastError || media.liveKitReason) && (
                <div className="mt-4 rounded-md border border-hairline bg-black/30 p-4 text-body-sm text-gradient-coral">
                  {media.mediaError || media.speechError || lastError || media.liveKitReason}
                </div>
              )}
            </div>

            <div className="rounded-lg border border-hairline bg-surface-2 p-5">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h3 className="text-body font-semibold text-ink">Camera Preview</h3>
                <Badge variant="outline" className="border-hairline text-ink-muted">
                  {media.cameraEnabled && media.cameraDeviceReady ? "Live" : media.cameraEnabled ? "Starting" : "Off"}
                </Badge>
              </div>
              <div className="relative aspect-video overflow-hidden rounded-md border border-hairline bg-black">
                <video
                  ref={previewVideoRef}
                  autoPlay
                  muted
                  playsInline
                  className={cn(
                    "h-full w-full object-cover transition-opacity",
                    media.cameraEnabled && media.cameraDeviceReady ? "opacity-100" : "opacity-0"
                  )}
                />
                {(!media.cameraEnabled || !media.cameraDeviceReady) && (
                  <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-black/80 text-ink-muted">
                    {media.cameraEnabled ? <Camera className="h-6 w-6" /> : <CameraOff className="h-6 w-6" />}
                    <span className="text-caption">{media.cameraEnabled ? "Camera starting" : "Camera off"}</span>
                  </div>
                )}
                <div className="absolute bottom-3 left-3 right-3 flex items-center gap-2 rounded-full bg-black/70 px-3 py-2 backdrop-blur">
                  {media.micEnabled ? <Mic className="h-4 w-4 text-semantic-success" /> : <MicOff className="h-4 w-4 text-gradient-coral" />}
                  <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-white/15">
                    <div className="h-full rounded-full bg-semantic-success transition-[width]" style={{ width: `${Math.round(media.audioLevel * 100)}%` }} />
                  </div>
                  <span className="text-caption text-ink-muted">
                    {media.micEnabled ? (media.micDeviceReady ? "Mic live" : "Mic starting") : "Mic muted"}
                  </span>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {phase === "active" && (
        <div className="relative h-screen w-screen overflow-hidden bg-black text-ink">
          <video
            ref={videoRef}
            autoPlay
            muted
            playsInline
            className={cn("absolute inset-0 h-full w-full object-cover transition-opacity", media.cameraEnabled && media.cameraDeviceReady ? "opacity-100" : "opacity-0")}
          />
          {(!media.cameraEnabled || !media.cameraDeviceReady) && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black text-ink-muted">
              {media.cameraEnabled ? <Camera className="h-10 w-10" /> : <CameraOff className="h-10 w-10" />}
              <span className="text-body-sm">{media.cameraEnabled ? "Camera unavailable" : "Camera off"}</span>
            </div>
          )}
          <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/15 to-black/45" />

          <div className="absolute left-4 top-4 flex flex-wrap items-center gap-3">
            <Badge className="bg-black/60 text-ink backdrop-blur">
              <Timer className="mr-1 h-3.5 w-3.5" />
              {formatClock(remainingSeconds)}
            </Badge>
            <Badge className="bg-black/60 text-ink backdrop-blur">
              Question {displayedQuestionNumber}/{questions.length}
            </Badge>
            <Badge className="bg-black/60 text-ink backdrop-blur">
              {selectedMode === "code" ? "Code answer" : listenMode === "consent" ? "Waiting for yes" : "Spoken answer"}
            </Badge>
            <Badge className={cn("bg-black/60 text-ink backdrop-blur", media.isListening && media.micEnabled && media.micDeviceReady && "bg-semantic-success/80 text-black")}>
              {micBadgeText}
            </Badge>
            <Badge className={cn("bg-black/60 text-ink backdrop-blur", media.liveKitConnected && "bg-semantic-success/80 text-black")}>
              {media.liveKitConnected ? <Wifi className="mr-1 h-3.5 w-3.5" /> : <WifiOff className="mr-1 h-3.5 w-3.5" />}
              {realtimeBadgeText}
            </Badge>
            <Badge className={cn("bg-black/60 text-ink backdrop-blur", media.transcriptionConnected && "bg-semantic-success/80 text-black")}>
              {transcriptionBadgeText}
            </Badge>
          </div>

          <div className="absolute right-5 top-5 flex w-[min(30vw,260px)] min-w-[150px] flex-col items-center">
            <div className="relative w-full">
              <Image
                src={profile.asset}
                alt=""
                width={520}
                height={520}
                sizes="(max-width: 768px) 150px, 260px"
                className={cn("mx-auto max-h-[34vh] w-full object-contain object-bottom", botSpeaking && "animate-pulse")}
                style={{
                  filter:
                    "drop-shadow(3px 0 #22c55e) drop-shadow(-3px 0 #22c55e) drop-shadow(0 3px #22c55e) drop-shadow(0 -3px #22c55e) drop-shadow(0 12px 24px rgba(0,0,0,.65))",
                }}
              />
              {botSpeaking && (
                <div className="absolute bottom-4 left-1/2 flex -translate-x-1/2 items-end gap-1 rounded-full bg-black/50 px-3 py-2">
                  {[0, 1, 2, 3].map((bar) => (
                    <span key={bar} className="h-3 w-1 animate-pulse rounded-full bg-semantic-success" style={{ animationDelay: `${bar * 90}ms` }} />
                  ))}
                </div>
              )}
            </div>
            <div className="mt-2 flex items-center gap-2 rounded-full bg-black/60 px-3 py-1 text-caption backdrop-blur">
              <Volume2 className="h-3.5 w-3.5 text-semantic-success" />
              {profile.name}
            </div>
          </div>

          <div className="absolute bottom-5 left-1/2 w-[min(920px,calc(100vw-2rem))] -translate-x-1/2">
            <div ref={transcriptScrollRef} className="max-h-[36vh] overflow-y-auto rounded-lg border border-white/10 bg-black/70 p-4 backdrop-blur-md">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h3 className="text-body font-semibold text-ink">Live Transcript</h3>
                <span className="text-caption text-ink-muted">
                  {listenMode === "answer" ? "Mic is listening" : botSpeaking ? "Bot speaking" : "Call active"}
                </span>
              </div>
              <div className="space-y-2">
                {currentTranscript.map((line) => (
                  <div
                    key={line.id}
                    className={cn(
                      "rounded-md px-3 py-2 text-body-sm",
                      line.speaker === "bot" && "bg-primary/20 text-ink",
                      line.speaker === "user" && "bg-white/10 text-ink-muted",
                      line.speaker === "system" && "bg-semantic-success/15 text-semantic-success"
                    )}
                  >
                    <span className="mr-2 text-caption uppercase text-ink-muted">
                      {line.speaker === "bot" ? profile.name : line.speaker}
                    </span>
                    <span className="whitespace-pre-wrap break-words">{line.text}</span>
                  </div>
                ))}
                {(partialTranscript || media.partialTranscript) && (
                  <div className="rounded-md bg-white/5 px-3 py-2 text-body-sm italic text-ink-muted">
                    {partialTranscript || media.partialTranscript}
                  </div>
                )}
              </div>
            </div>

            <div className="mt-3 space-y-3">
              <div className="flex flex-wrap items-center justify-center gap-2">
                {listenMode === "consent" && (
                  <>
                    <Button
                      type="button"
                      onClick={() =>
                        void speakBot("Great. I will ask one question at a time. Please answer naturally, and I will keep the timer for you.").then(() =>
                          askQuestionRef.current(runtimeStartIndexRef.current)
                        )
                      }
                      disabled={isRoundBlocked}
                      className="bg-primary text-on-primary"
                    >
                      <CheckCircle2 className="mr-2 h-4 w-4" />
                      Yes, Start
                    </Button>
                    <Button
                      type="button"
                      onClick={() => void speakBot("No problem. Take a moment. Click yes or say yes when you are ready to begin.").then(() => setListenMode("consent"))}
                      disabled={isRoundBlocked}
                      variant="outline"
                      className="border-white/20 bg-black/50 text-ink"
                    >
                      Not Yet
                    </Button>
                  </>
                )}
                {selectedMode === "spoken" && listenMode !== "consent" && (
                  <>
                    <Button
                      type="button"
                      onClick={submitSpokenNow}
                      disabled={isSubmitting || !selectedQuestion || isRoundBlocked}
                      className="bg-primary text-on-primary"
                    >
                      {isSubmitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Send className="mr-2 h-4 w-4" />}
                      Submit Answer
                    </Button>
                    <Button
                      type="button"
                      onClick={() =>
                        selectedQuestion &&
                        void submitQuestion(selectedQuestion, currentIndex, {
                          answer: answers[selectedQuestion.id] || "",
                          answerSource: "pass",
                        })
                      }
                      disabled={isSubmitting || !selectedQuestion || isRoundBlocked}
                      variant="outline"
                      className="border-white/20 bg-black/50 text-ink"
                    >
                      <PauseCircle className="mr-2 h-4 w-4" />
                      Pass
                    </Button>
                  </>
                )}
                {selectedMode === "code" && listenMode !== "consent" && (
                  <Button
                    type="button"
                    onClick={() => {
                      cancelBotSpeech();
                      setCodeDialogOpen(true);
                    }}
                    disabled={isRoundBlocked}
                    className="bg-primary text-on-primary"
                  >
                    <Code2 className="mr-2 h-4 w-4" />
                    Open Code Editor
                  </Button>
                )}
                {(listenMode === "consent" || selectedMode === "spoken") && media.micEnabled && !botSpeaking && (
                  <Button
                    type="button"
                    onClick={() => setListenMode(listenMode === "idle" ? "answer" : listenMode)}
                    disabled={isRoundBlocked || !media.micDeviceReady}
                    variant="outline"
                    className="border-white/20 bg-black/50 text-ink"
                  >
                    <Mic className="mr-2 h-4 w-4" />
                    {media.isListening ? "Restart Listening" : "Start Listening"}
                  </Button>
                )}
              </div>

              {(media.speechError || media.speechStatus || lastError) && (
                <p className="text-center text-caption text-ink-muted">{media.speechError || lastError || media.speechStatus}</p>
              )}

              <div className="mx-auto flex w-fit max-w-full flex-wrap items-center justify-center gap-2 rounded-full border border-white/10 bg-black/70 p-2 shadow-2xl backdrop-blur">
                <Button
                  type="button"
                  title={media.micEnabled ? "Mute microphone" : "Unmute microphone"}
                  aria-label={media.micEnabled ? "Mute microphone" : "Unmute microphone"}
                  onClick={() => void toggleMic()}
                  disabled={isRoundBlocked}
                  size="icon-lg"
                  variant="outline"
                  className={cn(
                    "rounded-full border-white/20 bg-white/10 text-ink hover:bg-white/15",
                    !media.micEnabled && "border-gradient-coral/70 bg-gradient-coral/20"
                  )}
                >
                  {media.micEnabled ? <Mic className="h-4 w-4" /> : <MicOff className="h-4 w-4" />}
                </Button>
                <Button
                  type="button"
                  title={media.cameraEnabled ? "Turn camera off" : "Turn camera on"}
                  aria-label={media.cameraEnabled ? "Turn camera off" : "Turn camera on"}
                  onClick={() => void toggleCamera()}
                  disabled={isRoundBlocked}
                  size="icon-lg"
                  variant="outline"
                  className={cn(
                    "rounded-full border-white/20 bg-white/10 text-ink hover:bg-white/15",
                    !media.cameraEnabled && "border-gradient-coral/70 bg-gradient-coral/20"
                  )}
                >
                  {media.cameraEnabled ? <Camera className="h-4 w-4" /> : <CameraOff className="h-4 w-4" />}
                </Button>
                <Button
                  type="button"
                  title="Repeat question"
                  aria-label="Repeat question"
                  onClick={repeatQuestionNow}
                  disabled={!selectedQuestion || botSpeaking || isRoundBlocked}
                  size="icon-lg"
                  variant="outline"
                  className="rounded-full border-white/20 bg-white/10 text-ink hover:bg-white/15"
                >
                  <Repeat2 className="h-4 w-4" />
                </Button>
                <Button
                  type="button"
                  title="Paraphrase question"
                  aria-label="Paraphrase question"
                  onClick={() => void paraphraseQuestionNow()}
                  disabled={!selectedQuestion || botSpeaking || isRoundBlocked}
                  size="icon-lg"
                  variant="outline"
                  className="rounded-full border-white/20 bg-white/10 text-ink hover:bg-white/15"
                >
                  <Sparkles className="h-4 w-4" />
                </Button>
                <Button
                  type="button"
                  onClick={() => void endCallNow()}
                  className="rounded-full bg-red-600 px-4 text-white hover:bg-red-500"
                >
                  <PhoneOff className="mr-2 h-4 w-4" />
                  End Call
                </Button>
              </div>
            </div>
          </div>

          {!fullscreenBlock && (warningMessage || clearSpeechMessage || lastError) && (
            <div className="absolute left-1/2 top-20 w-[min(640px,calc(100vw-2rem))] -translate-x-1/2 rounded-lg border border-semantic-success/50 bg-black/85 p-4 text-center text-body-sm text-ink shadow-xl backdrop-blur">
              <AlertTriangle className="mx-auto mb-2 h-5 w-5 text-semantic-success" />
              {warningMessage || clearSpeechMessage || lastError}
            </div>
          )}

          {fullscreenBlock && (
            <div className="absolute inset-0 z-40 flex items-center justify-center bg-black/85 p-4 backdrop-blur-md">
              <div className="w-[min(560px,calc(100vw-2rem))] rounded-lg border border-semantic-success/60 bg-surface-1 p-6 text-center shadow-2xl">
                <ShieldAlert className="mx-auto mb-4 h-10 w-10 text-semantic-success" />
                <h3 className="text-headline text-ink">{fullscreenBlock.mode === "recover" ? "Return to Fullscreen" : "Call Locked"}</h3>
                <p className="mx-auto mt-3 max-w-lg break-words text-body-sm text-ink-muted">{fullscreenBlock.message}</p>
                <div className="mt-6 flex flex-col justify-center gap-3 sm:flex-row">
                  {fullscreenBlock.mode === "recover" ? (
                    <Button type="button" onClick={() => void restoreFullscreen()} className="bg-primary text-on-primary">
                      <Maximize2 className="mr-2 h-4 w-4" />
                      Re-enter Fullscreen
                    </Button>
                  ) : (
                    <Button type="button" onClick={() => void endCallNow()} className="bg-red-600 text-white hover:bg-red-500">
                      <PhoneOff className="mr-2 h-4 w-4" />
                      End Call
                    </Button>
                  )}
                  <Button type="button" variant="outline" onClick={restartSameRound} className="border-hairline">
                    Restart This Round
                  </Button>
                </div>
              </div>
            </div>
          )}

          {codeDialogOpen && selectedMode === "code" && (
            <div className="absolute inset-0 z-30 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
              <div className="flex max-h-[calc(100vh-2rem)] w-[min(1000px,calc(100vw-2rem))] flex-col overflow-hidden rounded-lg border border-hairline bg-surface-1 text-ink shadow-2xl">
                <div className="flex items-center justify-between gap-3 border-b border-hairline p-4">
                  <h3 className="text-headline text-ink">Code Answer</h3>
                  <Badge variant="outline" className="border-hairline text-ink-muted">
                    {formatClock(remainingSeconds)}
                  </Badge>
                </div>
                <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
                  <div className="rounded-md border border-hairline bg-surface-2 p-3 text-body-sm text-ink-muted">
                    {questionText(selectedQuestion)}
                  </div>
                  <div
                    className="overflow-hidden rounded-lg border border-hairline bg-[#0b0f14]"
                    onCopy={(event) => blockEditorClipboardEvent(event, showClipboardWarning)}
                    onCut={(event) => blockEditorClipboardEvent(event, showClipboardWarning)}
                    onPaste={(event) => blockEditorClipboardEvent(event, showClipboardWarning)}
                    onDrop={(event) => blockEditorClipboardEvent(event, showClipboardWarning)}
                    onContextMenu={(event) => blockEditorClipboardEvent(event, showClipboardWarning)}
                  >
                    <Editor
                      height="420px"
                      language={languageConfig.monaco}
                      theme="vs-dark"
                      value={selectedQuestion ? codeAnswers[selectedQuestion.id] || languageConfig.starter : ""}
                      onChange={(value) =>
                        selectedQuestion &&
                        setCodeAnswers((current) => ({
                          ...current,
                          [selectedQuestion.id]: value || "",
                        }))
                      }
                      onMount={(editor) => {
                        codeEditorGuardCleanupRef.current?.();
                        codeEditorGuardCleanupRef.current = installMonacoClipboardGuard(editor, showClipboardWarning);
                      }}
                      options={{
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
                <div className="flex flex-col-reverse gap-2 border-t border-hairline bg-surface-2 p-4 sm:flex-row sm:justify-end">
                  <Button type="button" variant="outline" onClick={() => submitCodeNow("dont_know")} className="border-hairline">
                    Don&apos;t Know
                  </Button>
                  <Button type="button" onClick={() => submitCodeNow("code_submit")} disabled={isSubmitting} className="bg-primary text-on-primary">
                    {isSubmitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Send className="mr-2 h-4 w-4" />}
                    Submit Code
                  </Button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {phase === "terminated" && (
        <Card className="border-hairline bg-surface-1">
          <CardContent className="py-16 text-center">
            <ShieldAlert className="mx-auto mb-4 h-12 w-12 text-gradient-coral" />
            <h3 className="mb-2 text-headline text-ink">Interview Call Ended</h3>
            <p className="mx-auto mb-6 max-w-2xl text-body text-ink-muted">
              {terminationMessage || "The call ended because the proctor detected a repeated security violation."}
            </p>
            <Button onClick={restartSameRound} className="rounded-md bg-primary text-on-primary">
              Restart This Round
            </Button>
          </CardContent>
        </Card>
      )}

      {phase === "evaluation" && (
        <div className="max-h-[calc(100vh-10rem)] space-y-6 overflow-y-auto pr-2">
          <Card className="border-hairline bg-surface-1">
            <CardHeader>
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div>
                  <CardTitle className="text-headline text-ink">{title} Evaluation</CardTitle>
                  <p className="mt-1 text-body-sm text-ink-muted">
                    Evidence-based scoring from answers, timers, realtime transcript confidence, and proctor observations.
                  </p>
                </div>
                <Badge variant="outline" className="w-fit border-hairline text-ink-muted">
                  {submittedCount}/{questions.length} scored
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {questions.map((question, index) => {
                const result = results[question.id];
                const mode = answerModeFor(round, question, index);
                const localAnswer = mode === "code" ? codeAnswers[question.id] || "" : answers[question.id] || "";
                const metrics =
                  metricsByQuestion[question.id] ||
                  result?.speechMetrics ||
                  emptySpeechMetrics(
                    forceFullEvaluation
                      ? "The call ended before speech was captured for this question."
                      : "No speech was captured for this question."
                  );
                const displayResult =
                  result ||
                  ({
                    id: question.id,
                    score: 0,
                    feedback: forceFullEvaluation
                      ? "The call ended before this question was answered."
                      : "No evaluation has been captured for this question yet.",
                    matchedKeywords: [],
                    answerMode: mode,
                    timeTakenSeconds: metrics.durationSeconds,
                    timerExpired: false,
                    speechMetrics: metrics,
                    proctorEvents: [],
                    repeatCount: 0,
                    paraphraseCount: 0,
                    answerSource: forceFullEvaluation ? "end_call" : "pending",
                  } satisfies AnswerRoundResult);
                const statusLabel = answerStatusLabel(mode, displayResult, localAnswer, metrics);
                const noSpeechCaptured = mode === "spoken" && !hasCapturedResultAnswer(displayResult, localAnswer, metrics);
                const confidenceLabel = noSpeechCaptured ? "No speech" : metrics.confidenceLabel;
                const questionEvents = roundProctorEvents.filter((event) => event.questionId === question.id);
                const codeLineCount = mode === "code" ? localAnswer.split(/\r?\n/).filter((line) => line.trim()).length : 0;
                return (
                  <div key={question.id} className="rounded-lg border border-hairline bg-surface-2 p-4">
                    <div className="mb-3 flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                      <div className="min-w-0">
                        <div className="mb-2 flex flex-wrap items-center gap-2">
                          <Badge variant="outline" className="border-hairline text-ink-muted">
                            Question {askedQuestionSequenceRef.current[question.id] || index + 1}
                          </Badge>
                          <Badge variant="outline" className="border-hairline text-ink-muted">
                            {statusLabel}
                          </Badge>
                          {displayResult.timerExpired && <Badge className="bg-gradient-coral text-on-primary">Time expired</Badge>}
                        </div>
                        <p className="break-words text-body font-medium text-ink">{questionText(question)}</p>
                      </div>
                      <div className="shrink-0 rounded-md border border-hairline bg-surface-1 px-4 py-3 text-right">
                        <p className="text-caption text-ink-muted">Score</p>
                        <p className="text-headline text-ink">{Math.round(displayResult.score || 0)}/100</p>
                      </div>
                    </div>

                    <p className="whitespace-pre-wrap break-words text-body-sm text-ink-muted">
                      {cleanGeneratedText(displayResult.feedback, "No feedback captured.")}
                    </p>

                    {mode === "code" ? (
                      <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-4">
                        <div className="rounded-md border border-hairline bg-surface-1 p-3">
                          <p className="text-caption text-ink-muted">Submission</p>
                          <p className="mt-1 text-body font-semibold text-ink">{localAnswer.trim() ? "Code submitted" : "No code"}</p>
                        </div>
                        <div className="rounded-md border border-hairline bg-surface-1 p-3">
                          <p className="text-caption text-ink-muted">Evaluation Mode</p>
                          <p className="mt-1 text-body font-semibold text-ink">Code only</p>
                        </div>
                        <div className="rounded-md border border-hairline bg-surface-1 p-3">
                          <p className="text-caption text-ink-muted">Code Lines</p>
                          <p className="mt-1 text-body font-semibold text-ink">{codeLineCount}</p>
                        </div>
                        <div className="rounded-md border border-hairline bg-surface-1 p-3">
                          <p className="text-caption text-ink-muted">Duration</p>
                          <p className="mt-1 text-body font-semibold text-ink">{formatClock(metrics.durationSeconds || 0)}</p>
                        </div>
                      </div>
                    ) : (
                      <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-4">
                        <div className="rounded-md border border-hairline bg-surface-1 p-3">
                          <p className="text-caption text-ink-muted">Confidence</p>
                          <p className="mt-1 text-body font-semibold capitalize text-ink">{confidenceLabel}</p>
                        </div>
                        <div className="rounded-md border border-hairline bg-surface-1 p-3">
                          <p className="text-caption text-ink-muted">Recognition</p>
                          <p className="mt-1 text-body font-semibold text-ink">{Math.round((metrics.averageConfidence || 0) * 100)}%</p>
                        </div>
                        <div className="rounded-md border border-hairline bg-surface-1 p-3">
                          <p className="text-caption text-ink-muted">Pace</p>
                          <p className="mt-1 text-body font-semibold text-ink">{metrics.wordsPerMinute || 0} wpm</p>
                        </div>
                        <div className="rounded-md border border-hairline bg-surface-1 p-3">
                          <p className="text-caption text-ink-muted">Pauses</p>
                          <p className="mt-1 text-body font-semibold text-ink">{metrics.longPauseCount || 0}</p>
                        </div>
                      </div>
                    )}

                    {metrics?.notes && metrics.notes.length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {metrics.notes.map((note, noteIndex) => (
                          <span key={`${question.id}-note-${noteIndex}`} className="max-w-full rounded-sm border border-hairline px-2 py-1 text-caption text-ink-muted">
                            {cleanGeneratedText(note)}
                          </span>
                        ))}
                      </div>
                    )}

                    {questionEvents.length > 0 && (
                      <div className="mt-3 rounded-md border border-hairline bg-black/20 p-3">
                        <p className="mb-2 text-caption uppercase text-ink-muted">Proctor observations</p>
                        <div className="space-y-1">
                          {questionEvents.map((event) => (
                            <p key={event.id} className="break-words text-caption text-ink-muted">
                              {cleanGeneratedText(event.message)}
                            </p>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}

              {roundProctorEvents.length > 0 && (
                <div className="rounded-lg border border-hairline bg-surface-2 p-4">
                  <h3 className="mb-2 text-body font-semibold text-ink">Security Summary</h3>
                  <p className="text-body-sm text-ink-muted">
                    {roundProctorEvents.length} proctor event{roundProctorEvents.length > 1 ? "s" : ""} recorded during this round.
                  </p>
                </div>
              )}

              <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                <Button
                  type="button"
                  onClick={completeRound}
                  disabled={!allSubmitted || completionDisabled || isCompleting}
                  className="rounded-md bg-primary text-on-primary"
                >
                  {isCompleting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Sparkles className="mr-2 h-4 w-4" />}
                  {isCompleting ? "Working..." : nextLabel}
                </Button>
                {completionContent}
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      <InAppConfirmDialog
        open={endCallConfirmMode !== null}
        title={endCallConfirmMode === "locked" ? "End Locked Call" : "End Interview Call"}
        description={
          endCallConfirmMode === "locked"
            ? "End this locked call now? You can restart this round from the next screen."
            : "End the interview call now? Unanswered questions will be submitted as no answer so the evaluation panel can be completed."
        }
        confirmLabel={endCallConfirmMode === "locked" ? "End Locked Call" : "End Call"}
        variant="danger"
        onOpenChange={(open) => {
          if (!open) setEndCallConfirmMode(null);
        }}
        onConfirm={() => {
          const mode = endCallConfirmMode;
          if (mode) void endCallNow(mode);
        }}
      />
    </div>
  );
}
