// ============================================
// USER & AUTHENTICATION TYPES
// ============================================

export interface User {
  id: string;
  name: string;
  email: string;
  avatar?: string;
  createdAt: Date;
  updatedAt: Date;
}

export interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
}

// ============================================
// INTERVIEW WORKFLOW TYPES
// ============================================

export type InterviewStep = "form" | "dsa" | "aptitude" | "technical" | "hr";

export type BackendWorkflowStep = "dsa" | "aptitude" | "technical" | "hr" | "completed";

export interface WorkflowAllowedAction {
  action: string;
  targetStep?: BackendWorkflowStep;
  label?: string;
}

export interface WorkflowRoundProgress {
  completed: number;
  total: number;
  isComplete: boolean;
}

export interface WorkflowJobState {
  id: string;
  status: string;
  kind: string;
  currentNode: string;
  queueBackend?: string | null;
  externalJobId?: string | null;
  workerId?: string | null;
  queuePosition?: number | null;
  queueDepth?: number | null;
  leaseExpiresAt?: string | null;
  visibilityTimeoutSeconds?: number | null;
  attempt?: number;
  maxAttempts?: number;
  cancelRequested?: boolean;
  result?: Record<string, unknown>;
  error?: string | null;
  queuedAt?: string | null;
  startedAt?: string | null;
  finishedAt?: string | null;
  lastHeartbeatAt?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
  elapsedSeconds?: number | null;
  heartbeatAgeSeconds?: number | null;
  isStale?: boolean;
  staleReason?: string | null;
}

export interface WorkflowEvent {
  id: string;
  timestamp: string;
  type: "info" | "success" | "error" | "warning" | string;
  agent: string;
  message: string;
  step: BackendWorkflowStep | string;
  metadata?: Record<string, unknown>;
}

export interface WorkflowOrchestrationProof {
  graphName: string;
  graphNodes: Array<{ id: string; agent: string; stage: string }>;
  currentNode: string;
  currentAgent: string;
  agentCount: number;
  agentsObserved: string[];
  toolDecisionCount: number;
  toolResultCount: number;
  blackboardCheckpointCount: number;
  planningCritiqueCount: number;
  reviewerCritiqueCount: number;
  sectionReviewCount: number;
  collaborationTurnCount: number;
  fallbackUsed: boolean;
  artifactCounts: {
    dsa: number;
    aptitude: number;
    technical: number;
    hr: number;
  };
  timings: Record<string, unknown>;
  latestEvents: WorkflowEvent[];
}

export interface WorkflowState {
  interviewId: string;
  currentStep: BackendWorkflowStep;
  status: string;
  job: WorkflowJobState;
  events: WorkflowEvent[];
  orchestration?: WorkflowOrchestrationProof;
  roundProgress: Partial<Record<BackendWorkflowStep, WorkflowRoundProgress>>;
  allowedActions: WorkflowAllowedAction[];
  nextAction?: WorkflowAllowedAction | null;
}

export type DifficultyLevel = "easy" | "medium" | "hard";

export type CompanyStyle = "faang" | "startup" | "enterprise" | "product";

export interface InterviewFormData {
  name: string;
  email: string;
  role: string;
  companyStyle: CompanyStyle;
  difficulty: DifficultyLevel;
  jobDescription: string;
  resume: File | null;
  skills: string[];
  language: string;
}

export interface DSASubmission {
  code: string;
  language: string;
  problemId: string;
  timestamp: Date;
}

export interface DSAProblem {
  id: string;
  interview_id: string;
  problem_number: number;
  category?: string;
  title: string;
  description: string;
  difficulty: DifficultyLevel | string;
  examples: Array<Record<string, any>>;
  test_cases?: Array<Record<string, any>>;
  constraints?: string;
  tags: string[];
}

export interface AptitudeQuestion {
  id: string;
  interview_id?: string;
  question_number?: number;
  question?: string;
  question_text?: string;
  options: string[] | Record<string, string>;
  difficulty?: DifficultyLevel | string;
  category?: string;
}

export interface InterviewQuestion {
  id: string;
  interview_id?: string;
  question_number?: number;
  question_text: string;
  role?: string;
  difficulty?: DifficultyLevel | string;
  keywords?: string[];
  answer_mode?: "spoken" | "code";
  timer_seconds?: number;
}

export interface GeneratedInterviewAssets {
  interviewId: string | null;
  dsaProblems: DSAProblem[];
  aptitudeQuestions: AptitudeQuestion[];
  technicalQuestions: InterviewQuestion[];
  hrQuestions: InterviewQuestion[];
}

export interface AptitudeAnswer {
  questionId: string;
  selectedOption: string | string[];
  timestamp: Date;
}

export interface DSATestResult {
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
}

export interface DSAEvaluationEntry {
  id: string;
  problemId: string;
  action: "run" | "submit";
  status: string;
  score: number;
  feedback: string;
  testResults: DSATestResult[];
  timestamp: Date;
  language: string;
}

export interface AptitudeRoundResult {
  score: number;
  correct: number;
  wrong: number;
  timeTakenSeconds?: number;
  per_question_results: Array<{
    question_id: string;
      selected?: string;
      selected_value?: string;
      correct: string;
      correct_value?: string;
      correct_options?: string[];
      correct_values?: string[];
      accepted_options?: string[];
      accepted_values?: string[];
      is_correct: boolean;
      explanation: string;
      answer_key_corrected?: boolean;
      original_correct_answer?: string;
      ambiguous_question?: boolean;
    }>;
  }

export interface AnswerRoundResult {
  id: string;
  score: number;
  feedback: string;
  matchedKeywords?: string[];
  answerMode?: "spoken" | "code";
  timeTakenSeconds?: number;
  timerExpired?: boolean;
  speechMetrics?: SpeechMetrics;
  proctorEvents?: ProctorEvent[];
  repeatCount?: number;
  paraphraseCount?: number;
  answerSource?: string;
}

export interface InterviewState {
  currentStep: InterviewStep;
  interviewSessionStatus: "idle" | "active" | "stopped" | "completed";
  roundRestartKeys: Record<Exclude<InterviewStep, "form">, number>;
  backendWorkflowEnabled: boolean;
  workflowState: WorkflowState | null;
  workflowError: string | null;
  formData: InterviewFormData;
  dsaSubmissions: DSASubmission[];
  dsaEvaluationHistory: DSAEvaluationEntry[];
  aptitudeAnswers: AptitudeAnswer[];
  aptitudeResult: AptitudeRoundResult | null;
  technicalResults: Record<string, AnswerRoundResult>;
  hrResults: Record<string, AnswerRoundResult>;
  technicalTranscript: TranscriptEntry[];
  hrTranscript: TranscriptEntry[];
  isProcessing: boolean;
  isNavigationLocked: boolean;
  executionLogs: ExecutionLog[];
  interviewId: string | null;
  dsaProblems: DSAProblem[];
  aptitudeQuestions: AptitudeQuestion[];
  technicalQuestions: InterviewQuestion[];
  hrQuestions: InterviewQuestion[];
}

export interface ExecutionLog {
  id: string;
  timestamp: Date;
  type: "info" | "success" | "error" | "warning";
  agent: string;
  message: string;
}

export interface TranscriptEntry {
  id: string;
  timestamp: Date;
  speaker: "ai" | "user";
  text: string;
  confidence?: number;
}

export interface SpeechMetrics {
  averageConfidence: number;
  wordsPerMinute: number;
  durationSeconds: number;
  longPauseCount: number;
  unclearCount: number;
  transcriptWords: number;
  confidenceLabel: "strong" | "steady" | "hesitant" | "unclear";
  notes: string[];
  realtimeSignals?: Array<{
    type: "non_answer" | "off_topic" | "unsafe" | "low_relevance" | "substantive";
    severity: "info" | "warning" | "critical";
    message: string;
    timestamp: string;
    excerpt?: string;
  }>;
}

export interface ProctorEvent {
  id: string;
  type:
    | "visibility"
    | "focus"
    | "fullscreen"
    | "cursor"
    | "media"
    | "face"
    | "object"
    | "speech";
  severity: "warning" | "critical";
  message: string;
  timestamp: string;
  questionId?: string;
}

// ============================================
// REPORT TYPES
// ============================================

export interface Report {
  id: string;
  userId: string;
  interviewId: string;
  createdAt: Date;
  overallScore: number;
  sections: ReportSection[];
  strengths: string[];
  weaknesses: string[];
  aiFeedback: string;
  executiveSummary?: string;
  whatWentWrong?: string[];
  nextTimeSuggestions?: string[];
  actionPlan?: ReportActionItem[];
  sectionAnalyses?: Array<Record<string, any>>;
  generationProvider?: string | null;
  communicationSummary?: Record<string, any>;
  proctorSummary?: Record<string, any>;
  transcript: TranscriptEntry[];
}

export interface ReportSection {
  name: string;
  score: number;
  maxScore: number;
  feedback: string;
  details: Record<string, any>;
}

export interface ReportActionItem {
  id?: string;
  title: string;
  description: string;
  priority: string;
}

export interface ReportState {
  reports: Report[];
  currentReport: Report | null;
  isLoading: boolean;
}

// ============================================
// ROADMAP TYPES
// ============================================

export interface Roadmap {
  id: string;
  userId: string;
  title: string;
  description: string;
  createdAt: Date;
  updatedAt: Date;
  milestones: Milestone[];
  skills: SkillNode[];
  progress: number;
  isActive: boolean;
}

export interface Milestone {
  id: string;
  title: string;
  description: string;
  dueDate: Date;
  completed: boolean;
  tasks: Task[];
}

export interface Task {
  id: string;
  title: string;
  description?: string;
  completed: boolean;
  priority: "low" | "medium" | "high";
}

export interface SkillNode {
  id: string;
  name: string;
  category: string;
  level: number;
  targetLevel: number;
  resources: Resource[];
}

export interface Resource {
  id: string;
  title: string;
  type: "article" | "video" | "course" | "book";
  url: string;
  completed: boolean;
}

export interface RoadmapState {
  roadmaps: Roadmap[];
  activeRoadmap: Roadmap | null;
  isLoading: boolean;
}

// ============================================
// PRACTICE ARENA TYPES
// ============================================

export type PracticeMode = "dsa" | "aptitude" | "mixed";

export interface PracticeSession {
  id: string;
  userId: string;
  mode: PracticeMode;
  difficulty: DifficultyLevel;
  startedAt: Date;
  endedAt?: Date;
  score: number;
  questions: PracticeQuestion[];
}

export interface PracticeQuestion {
  id: string;
  type: "coding" | "mcq";
  difficulty: DifficultyLevel;
  category: string;
  question: string;
  answer?: string;
  isCorrect?: boolean;
}

// ============================================
// RESUME ANALYSIS TYPES
// ============================================

export interface ResumeAnalysis {
  id: string;
  userId: string;
  fileName: string;
  uploadedAt: Date;
  atsScore: number;
  keywords: KeywordAnalysis;
  suggestions: ResumeSuggestion[];
  formatIssues: string[];
}

export interface KeywordAnalysis {
  found: string[];
  missing: string[];
  frequency: Record<string, number>;
}

export interface ResumeSuggestion {
  section: string;
  type: "add" | "remove" | "modify";
  original?: string;
  suggested: string;
  reason: string;
}

// ============================================
// AI BOT TYPES
// ============================================

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  context?: ChatContext;
}

export interface ChatContext {
  reportId?: string;
  roadmapId?: string;
  resumeId?: string;
  relevantData?: Record<string, any>;
}

export interface ChatState {
  messages: ChatMessage[];
  isStreaming: boolean;
  context: ChatContext | null;
}

// ============================================
// SETTINGS TYPES
// ============================================

export interface UserSettings {
  profile: ProfileSettings;
  ai: AISettings;
  memory: MemorySettings;
  integrations: IntegrationSettings;
  appearance: AppearanceSettings;
  security: SecuritySettings;
  notifications: NotificationSettings;
  interview: InterviewSettings;
}

export interface ProfileSettings {
  name: string;
  email: string;
  avatar?: string;
  headline?: string;
  location?: string;
  website?: string;
  linkedin?: string;
  github?: string;
  bio?: string;
  socialLinks?: Record<string, string>;
}

export interface AISettings {
  defaultDifficulty: DifficultyLevel;
  personality: "professional" | "friendly" | "direct";
  voiceEnabled: boolean;
  language: string;
  interviewVoiceProfile?: string;
  memoryEnabled?: boolean;
  responseStyle?: "concise" | "balanced" | "detailed";
}

export interface MemorySettings {
  dataRetentionDays: number;
  allowDataCollection: boolean;
  storeChatHistory?: boolean;
  includeResumeContext?: boolean;
}

export interface IntegrationSettings {
  calendar?: {
    enabled: boolean;
    provider: string;
  };
  linkedin?: {
    connected: boolean;
  };
  github?: {
    connected: boolean;
  };
}

export interface AppearanceSettings {
  theme: "dark" | "light";
  accentColor: string;
  fontSize: "small" | "medium" | "large";
  compactDashboard?: boolean;
  reduceMotion?: boolean;
}

export interface SecuritySettings {
  twoFactorEnabled: boolean;
  activeSessions: Session[];
}

export interface NotificationSettings {
  emailReports: boolean;
  weeklyDigest: boolean;
  practiceReminders: boolean;
  roadmapReminders: boolean;
}

export interface InterviewSettings {
  defaultRole: string;
  defaultCompanyStyle: CompanyStyle;
  defaultLanguage: string;
  practiceQuestionCount: number;
  showExecutionLogs: boolean;
  autoSaveAnswers: boolean;
}

export interface Session {
  id: string;
  device: string;
  location: string;
  lastActive: Date;
}

// ============================================
// UI STATE TYPES
// ============================================

export interface SidebarState {
  isCollapsed: boolean;
  activeRoute: string;
}

export interface SettingsState {
  settings: UserSettings;
  isLoading: boolean;
}
