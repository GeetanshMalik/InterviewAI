"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent } from "@/components/ui/card";
import { useInterviewStore } from "@/stores/interview-store";
import { useAuthStore } from "@/stores/auth-store";
import { useSettingsStore } from "@/stores/settings-store";
import { apiService } from "@/services/api-service";
import type { AptitudeQuestion, DSAProblem, InterviewQuestion, UserSettings, WorkflowState } from "@/types";
import { ExecutionLogPanel } from "./execution-log-panel";
import { Check, ChevronDown, Search, Upload } from "lucide-react";
import { cn } from "@/lib/utils";
import { allJobRoles, jobRoleGroups } from "@/constants/job-roles";

type OpenDropdown = "role" | "company" | "difficulty" | null;

const fieldClass = "h-14 rounded-md bg-surface-2 border-hairline px-5 text-body text-ink";
const selectTriggerClass =
  "h-14 w-full rounded-md bg-surface-2 border-hairline px-5 text-body text-ink data-[size=default]:h-14";

function JobRoleSelector({
  value,
  onChange,
  isOpen,
  onOpenChange,
}: {
  value: string;
  onChange: (value: string) => void;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const handlePointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        onOpenChange(false);
      }
    };

    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [onOpenChange]);

  useEffect(() => {
    if (!isOpen) return;
    window.setTimeout(() => searchRef.current?.focus(), 0);
  }, [isOpen]);

  const filteredGroups = useMemo(() => {
    const search = query.trim().toLowerCase();
    if (!search) {
      return jobRoleGroups;
    }

    return jobRoleGroups
      .map((group) => ({
        ...group,
        roles: group.roles.filter((role) => role.toLowerCase().includes(search)),
      }))
      .filter((group) => group.roles.length > 0);
  }, [query]);

  const canUseCustomRole =
    query.trim().length > 1 &&
    !allJobRoles.some((role) => role.toLowerCase() === query.trim().toLowerCase());

  const chooseRole = (role: string) => {
    onChange(role);
    setQuery("");
    onOpenChange(false);
  };

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => onOpenChange(!isOpen)}
        className={cn(
          selectTriggerClass,
          "flex items-center justify-between gap-3 text-left outline-none focus:outline-none focus-visible:outline-none focus-visible:ring-0",
          !value && "text-ink-muted"
        )}
        aria-expanded={isOpen}
      >
        <span className="min-w-0 truncate">{value || "Search and select a job role"}</span>
        <ChevronDown className="h-4 w-4 shrink-0 text-ink" />
      </button>

      {isOpen && (
        <div className="absolute left-0 top-full z-50 mt-2 w-full overflow-hidden rounded-md border border-hairline bg-surface-1 shadow-xl">
          <div className="border-b border-hairline p-2">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" />
              <Input
                ref={searchRef}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Escape") {
                    onOpenChange(false);
                  }
                  if (event.key === "Enter") {
                    event.preventDefault();
                    const firstRole = filteredGroups[0]?.roles[0];
                    if (firstRole) {
                      chooseRole(firstRole);
                    } else if (canUseCustomRole) {
                      chooseRole(query.trim());
                    }
                  }
                }}
                placeholder="Search any technical or non-technical role..."
                className="h-12 rounded-md border-hairline bg-surface-2 pl-9 pr-3 text-body-sm"
              />
            </div>
          </div>

          <div className="max-h-80 overflow-y-auto p-1">
            {filteredGroups.map((group) => (
              <div key={group.group} className="py-1">
                <p className="px-3 py-1 text-micro uppercase tracking-wide text-ink-muted">
                  {group.group}
                </p>
                {group.roles.map((role) => (
                  <button
                    key={role}
                    type="button"
                    onMouseDown={(event) => {
                      event.preventDefault();
                      chooseRole(role);
                    }}
                    className={cn(
                      "flex w-full items-center justify-between gap-3 rounded-md px-3 py-2 text-left text-body-sm outline-none transition-colors hover:bg-surface-2 focus:bg-surface-2 focus:outline-none focus-visible:outline-none focus-visible:ring-0",
                      value === role ? "text-ink" : "text-ink-muted"
                    )}
                  >
                    <span className="min-w-0 truncate">{role}</span>
                    {value === role && <Check className="h-4 w-4 shrink-0 text-ink" />}
                  </button>
                ))}
              </div>
            ))}

            {canUseCustomRole && (
              <button
                type="button"
                onMouseDown={(event) => {
                  event.preventDefault();
                  chooseRole(query.trim());
                }}
                className="mt-1 flex w-full items-center justify-between gap-3 rounded-md border border-dashed border-hairline px-3 py-2 text-left text-body-sm text-ink outline-none hover:border-accent-blue/60 focus:outline-none focus-visible:outline-none focus-visible:ring-0"
              >
                <span className="min-w-0 truncate">Use "{query.trim()}"</span>
                <Check className="h-4 w-4 shrink-0 text-ink" />
              </button>
            )}

            {filteredGroups.length === 0 && !canUseCustomRole && (
              <p className="px-3 py-6 text-center text-body-sm text-ink-muted">
                Start typing to search or enter a custom role.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function OptionDropdown({
  value,
  options,
  isOpen,
  onOpenChange,
  onChange,
}: {
  value: string;
  options: Array<{ value: string; label: string }>;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onChange: (value: string) => void;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const selected = options.find((option) => option.value === value);

  useEffect(() => {
    const handlePointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        onOpenChange(false);
      }
    };

    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [onOpenChange]);

  const choose = (nextValue: string) => {
    onChange(nextValue);
    onOpenChange(false);
  };

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => onOpenChange(!isOpen)}
        className={cn(
          selectTriggerClass,
          "flex items-center justify-between gap-3 text-left outline-none focus:outline-none focus-visible:outline-none focus-visible:ring-0"
        )}
        aria-expanded={isOpen}
      >
        <span className="min-w-0 truncate">{selected?.label || value}</span>
        <ChevronDown className="h-4 w-4 shrink-0 text-ink" />
      </button>

      {isOpen && (
        <div className="absolute left-0 top-full z-50 mt-2 w-full overflow-hidden rounded-md border border-hairline bg-surface-1 shadow-xl">
          <div className="p-1">
            {options.map((option) => (
              <button
                key={option.value}
                type="button"
                onMouseDown={(event) => {
                  event.preventDefault();
                  choose(option.value);
                }}
                className={cn(
                  "flex w-full items-center justify-between gap-3 rounded-md px-3 py-2.5 text-left text-body-sm outline-none transition-colors hover:bg-surface-2 focus:bg-surface-2",
                  value === option.value ? "text-ink" : "text-ink-muted"
                )}
              >
                <span>{option.label}</span>
                {value === option.value && <Check className="h-4 w-4 shrink-0 text-ink" />}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

const companyStyleOptions = [
  { value: "faang", label: "FAANG" },
  { value: "startup", label: "Startup" },
  { value: "enterprise", label: "Enterprise" },
  { value: "product", label: "Product Company" },
];

const difficultyOptions = [
  { value: "easy", label: "Easy" },
  { value: "medium", label: "Medium" },
  { value: "hard", label: "Hard" },
];

async function requestInterviewFullscreen(addExecutionLog: (log: { type: "info" | "success" | "error" | "warning"; agent: string; message: string }) => void) {
  if (typeof document === "undefined" || document.fullscreenElement) return;
  const target = document.documentElement;
  if (!target.requestFullscreen) return;
  try {
    await target.requestFullscreen();
    addExecutionLog({
      type: "success",
      agent: "AI Proctor",
      message: "Fullscreen interview session started.",
    });
  } catch {
    addExecutionLog({
      type: "warning",
      agent: "AI Proctor",
      message: "Fullscreen permission was not granted. Re-enter fullscreen when the first round opens.",
    });
  }
}

export function FormTab() {
  const {
    formData,
    updateFormData,
    addExecutionLog,
    setGeneratedInterview,
    setCurrentStep,
    setInterviewSessionStatus,
    setNavigationLocked,
    setWorkflowState,
    workflowState,
    dsaProblems,
  } = useInterviewStore();
  const { user } = useAuthStore();
  const { settings, setSettings } = useSettingsStore();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [interviewId, setInterviewId] = useState<string | null>(null);
  const [isRetrying, setIsRetrying] = useState(false);
  const [openDropdown, setOpenDropdown] = useState<OpenDropdown>(null);
  const [formError, setFormError] = useState("");
  const defaultsAppliedRef = useRef(false);
  const touchedFieldsRef = useRef<Record<string, boolean>>({});
  const executionLogsEnabled = settings.interview.showExecutionLogs;
  const generationFailed =
    Boolean(workflowState && dsaProblems.length === 0) &&
    ["failed", "cancelled"].includes(String(workflowState?.job?.status || ""));
  const retryGenerationAvailable = Boolean(
    workflowState?.allowedActions?.some((action) => action.action === "retry_generation")
  );
  const generationStale = Boolean(workflowState?.job?.isStale && retryGenerationAvailable);
  const generationPending =
    Boolean(workflowState && dsaProblems.length === 0) &&
    ["ready", "queued", "running", "retrying"].includes(String(workflowState?.job?.status || "")) &&
    !generationStale;
  const generationRecoverable = generationFailed || generationStale;
  const queuePosition =
    typeof workflowState?.job?.queuePosition === "number" ? workflowState.job.queuePosition : null;
  const elapsedSeconds =
    typeof workflowState?.job?.elapsedSeconds === "number" ? workflowState.job.elapsedSeconds : null;
  const elapsedLabel =
    elapsedSeconds === null
      ? ""
      : elapsedSeconds < 60
      ? `${Math.round(elapsedSeconds)}s`
      : `${Math.floor(elapsedSeconds / 60)}m ${Math.round(elapsedSeconds % 60)}s`;
  const currentNode = workflowState?.job?.currentNode;
  const pendingStatus =
    workflowState?.job?.isStale
      ? "Workflow worker heartbeat is stale. Refreshing backend state..."
    : workflowState?.job?.status === "queued" && queuePosition !== null && queuePosition > 0
      ? queuePosition === 1
        ? "Next in Redis queue; waiting for worker pickup"
        : `Queued behind ${queuePosition - 1} job${queuePosition - 1 === 1 ? "" : "s"}`
    : workflowState?.job?.status === "queued"
      ? "Redis accepted the job; waiting for worker pickup"
      : workflowState?.job?.workerId
      ? `Worker ${workflowState.job.workerId} is running ${currentNode || "agent orchestration"}`
      : workflowState?.job?.status
      ? `Workflow status: ${workflowState.job.status}`
      : "";
  const pendingDetail = elapsedLabel ? `Elapsed ${elapsedLabel}` : "";

  useEffect(() => {
    if (!isSubmitting) return;
    const jobStatus = workflowState?.job?.status;
    if (dsaProblems.length > 0 && jobStatus === "succeeded") {
      setIsSubmitting(false);
      setCurrentStep("dsa");
      return;
    }
    if (jobStatus === "failed" || jobStatus === "cancelled") {
      setIsSubmitting(false);
      setInterviewSessionStatus("idle");
      setNavigationLocked(false);
      setCurrentStep("form");
    }
  }, [
    dsaProblems.length,
    isSubmitting,
    setCurrentStep,
    setInterviewSessionStatus,
    setNavigationLocked,
    workflowState?.job?.status,
  ]);

  const updateUserField = (field: string, value: unknown) => {
    touchedFieldsRef.current[field] = true;
    updateFormData({ [field]: value } as Partial<typeof formData>);
  };

  useEffect(() => {
    let mounted = true;

    const seedFormDefaults = (source: UserSettings) => {
      if (!mounted || defaultsAppliedRef.current) return;
      const current = useInterviewStore.getState().formData;
      const touched = touchedFieldsRef.current;

      updateFormData({
        name: touched.name ? current.name : current.name || source.profile.name || user?.name || "",
        email: touched.email ? current.email : current.email || source.profile.email || user?.email || "",
        role: touched.role ? current.role : current.role || source.interview.defaultRole || "",
        companyStyle: touched.companyStyle
          ? current.companyStyle
          : source.interview.defaultCompanyStyle || current.companyStyle,
        difficulty: touched.difficulty
          ? current.difficulty
          : source.ai.defaultDifficulty || current.difficulty,
        language: touched.language
          ? current.language
          : source.interview.defaultLanguage || current.language,
      });
      defaultsAppliedRef.current = true;
    };

    apiService
      .request<UserSettings>("/api/settings", { cacheTtlMs: 30_000 })
      .then((remote) => {
        if (!mounted) return;
        setSettings(remote);
        seedFormDefaults(remote);
      })
      .catch(() => {
        seedFormDefaults(useSettingsStore.getState().settings);
      });

    return () => {
      mounted = false;
    };
  }, [setSettings, user?.email, user?.name]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError("");
    if (!formData.role.trim()) {
      setFormError("Choose or enter a target role before starting the interview.");
      addExecutionLog({
        type: "error",
        agent: "Form Processor",
        message: "Please choose or enter a target role before starting the interview.",
      });
      return;
    }

    setIsSubmitting(true);
    setInterviewSessionStatus("active");
    setNavigationLocked(true);
    void requestInterviewFullscreen(addExecutionLog);

    addExecutionLog({
      type: "info",
      agent: "Form Processor",
      message: "Processing interview form data...",
    });

    try {
      const payload = new FormData();
      payload.append("name", formData.name);
      payload.append("email", formData.email);
      payload.append("role", formData.role);
      payload.append("companyStyle", formData.companyStyle);
      payload.append("difficulty", formData.difficulty);
      payload.append("jobDescription", formData.jobDescription);
      payload.append("language", formData.language);
      payload.append("skills", formData.skills.join(","));
      if (formData.resume) {
        payload.append("resume", formData.resume);
      }

      const response = await apiService.request<{
        interview: { id: string };
        dsa_problems: DSAProblem[];
        aptitude_questions: AptitudeQuestion[];
        technical_questions: InterviewQuestion[];
        hr_questions: InterviewQuestion[];
        workflow?: WorkflowState;
        assets_ready?: boolean;
      }>("/api/interviews?async_generation=true", {
        method: "POST",
        body: payload,
      });

      setInterviewId(response.interview.id);
      setGeneratedInterview({
        interviewId: response.interview.id,
        dsaProblems: response.dsa_problems,
        aptitudeQuestions: response.aptitude_questions,
        technicalQuestions: response.technical_questions,
        hrQuestions: response.hr_questions,
        workflowState: response.workflow ?? null,
      });
      addExecutionLog({
        type: "success",
        agent: "Interview API",
        message: `Interview ${response.interview.id} created successfully.`,
      });

      if (!response.assets_ready) {
        addExecutionLog({
          type: "info",
          agent: "Workflow Orchestrator Agent",
          message: "Autonomous interview preparation is running in the backend. Live agent workflow will appear here.",
        });
        setCurrentStep("form");
        return;
      }

      addExecutionLog({
        type: "success",
        agent: "Interview Orchestrator",
        message: "DSA test is ready. Opening the backend-selected DSA round...",
      });
      setIsSubmitting(false);
      setCurrentStep("dsa");
    } catch (error) {
      addExecutionLog({
        type: "error",
        agent: "Interview API",
        message: error instanceof Error ? error.message : "Unable to start interview",
      });
      setInterviewSessionStatus("idle");
      setNavigationLocked(false);
      setIsSubmitting(false);
    }
  };

  const handleRetryGeneration = async () => {
    if (!workflowState?.interviewId || !retryGenerationAvailable) return;
    setFormError("");
    setIsRetrying(true);
    setInterviewSessionStatus("active");
    setNavigationLocked(true);
    addExecutionLog({
      type: "warning",
      agent: "Workflow Orchestrator Agent",
      message: "Retrying interview generation with a fresh durable queue payload...",
    });
    try {
      const state = await apiService.request<WorkflowState>(
        `/api/interviews/${workflowState.interviewId}/actions`,
        {
          method: "POST",
          body: {
            action: "retry_generation",
            metadata: { source: "form_retry_button" },
          },
        }
      );
      setWorkflowState(state);
      addExecutionLog({
        type: "info",
        agent: "Workflow Orchestrator Agent",
        message: "Interview generation retry has been queued.",
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unable to retry interview generation.";
      setFormError(message);
      addExecutionLog({
        type: "error",
        agent: "Workflow Orchestrator Agent",
        message,
      });
      setInterviewSessionStatus("idle");
      setNavigationLocked(false);
    } finally {
      setIsRetrying(false);
    }
  };

  return (
    <div
      className={cn(
        "grid h-full min-h-0 grid-cols-1 gap-6 overflow-hidden",
        executionLogsEnabled && "lg:grid-cols-[minmax(0,1fr)_420px]"
      )}
    >
      <div className="h-full min-h-0">
        <Card className="flex h-full min-h-0 flex-col overflow-hidden bg-surface-1 border-hairline p-0">
          <CardContent className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden overscroll-contain px-4 pb-5 pt-6 [scrollbar-color:#2f3540_#111418] [scrollbar-width:thin] [&::-webkit-scrollbar]:w-2 [&::-webkit-scrollbar-track]:bg-[#111418] [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-white/20">
            <form onSubmit={handleSubmit} className="space-y-7">
              <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
                <div className="space-y-2">
                  <label className="text-body-sm text-ink">Full Name</label>
                  <Input
                    value={formData.name}
                    onChange={(e) => updateUserField("name", e.target.value)}
                    placeholder="John Doe"
                    required
                    className={fieldClass}
                  />
                </div>

                <div className="space-y-2">
                  <label className="text-body-sm text-ink">Email</label>
                  <Input
                    type="email"
                    value={formData.email}
                    onChange={(e) => updateUserField("email", e.target.value)}
                    placeholder="john@example.com"
                    required
                    className={fieldClass}
                  />
                </div>

                <div className="space-y-2">
                  <label className="text-body-sm text-ink">Target Role</label>
                  <JobRoleSelector
                    value={formData.role}
                    onChange={(role) => updateUserField("role", role)}
                    isOpen={openDropdown === "role"}
                    onOpenChange={(open) => setOpenDropdown(open ? "role" : null)}
                  />
                </div>

                <div className="space-y-2">
                  <label className="text-body-sm text-ink">Company Style</label>
                  <OptionDropdown
                    value={formData.companyStyle}
                    options={companyStyleOptions}
                    isOpen={openDropdown === "company"}
                    onOpenChange={(open) => setOpenDropdown(open ? "company" : null)}
                    onChange={(value) => updateUserField("companyStyle", value)}
                  />
                </div>

                <div className="space-y-2">
                  <label className="text-body-sm text-ink">Difficulty Level</label>
                  <OptionDropdown
                    value={formData.difficulty}
                    options={difficultyOptions}
                    isOpen={openDropdown === "difficulty"}
                    onOpenChange={(open) => setOpenDropdown(open ? "difficulty" : null)}
                    onChange={(value) => updateUserField("difficulty", value)}
                  />
                </div>
              </div>

              <div className="space-y-2">
                <label className="text-body-sm text-ink">Job Description</label>
                <Textarea
                  value={formData.jobDescription}
                  onChange={(e) => updateFormData({ jobDescription: e.target.value })}
                  placeholder="Paste the job description here..."
                  rows={4}
                  className="min-h-28 rounded-md bg-surface-2 border-hairline px-4 py-3 text-body text-ink"
                />
              </div>

              <div className="space-y-2">
                <label className="text-body-sm text-ink">Resume Upload</label>
                <div 
                  onClick={() => document.getElementById("resume-input")?.click()}
                  className={cn(
                    "border-2 border-dashed rounded-lg p-8 text-center transition-colors cursor-pointer",
                    formData.resume 
                      ? "border-primary bg-primary/5" 
                      : "border-hairline hover:border-accent-blue/50"
                  )}
                >
                  <Upload className={cn(
                    "w-8 h-8 mx-auto mb-2",
                    formData.resume ? "text-primary" : "text-ink-muted"
                  )} />
                  {formData.resume ? (
                    <div>
                      <p className="text-body-sm text-ink font-medium">
                        {formData.resume.name}
                      </p>
                      <p className="text-caption text-primary mt-1">
                        Click to change file
                      </p>
                    </div>
                  ) : (
                    <>
                      <p className="text-body-sm text-ink mb-1">
                        Click to upload or drag and drop
                      </p>
                      <p className="text-caption text-ink-muted">PDF, DOC up to 10MB</p>
                    </>
                  )}
                  <input 
                    id="resume-input"
                    type="file" 
                    className="hidden" 
                    accept=".pdf,.doc,.docx"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) {
                        updateFormData({ resume: file });
                        addExecutionLog({
                          type: "info",
                          agent: "System",
                          message: `Resume "${file.name}" uploaded.`,
                        });
                      }
                    }}
                  />
                </div>
              </div>

              {formError && (
                <div className="rounded-md border border-gradient-coral/40 bg-gradient-coral/10 px-4 py-3 text-body-sm text-gradient-coral">
                  {formError}
                </div>
              )}

              <Button
                type={generationRecoverable && retryGenerationAvailable ? "button" : "submit"}
                onClick={generationRecoverable && retryGenerationAvailable ? handleRetryGeneration : undefined}
                disabled={isSubmitting || isRetrying || generationPending}
                className="w-full bg-primary text-on-primary hover:bg-primary/90 rounded-pill"
              >
                {isSubmitting || isRetrying || generationPending
                  ? "Agents are preparing your interview..."
                  : generationRecoverable
                  ? generationStale
                    ? "Retry Stale Generation"
                    : "Retry Interview Generation"
                  : "Start Interview"}
              </Button>
              {generationPending && pendingStatus && (
                <p className="text-caption text-ink-muted text-center">
                  {pendingStatus}
                  {pendingDetail ? ` - ${pendingDetail}` : ""}
                </p>
              )}
              {interviewId && (
                <p className="text-caption text-ink-muted text-center">
                  Interview ID: {interviewId}
                </p>
              )}
            </form>
          </CardContent>
        </Card>
      </div>

      {executionLogsEnabled && (
        <div className="h-full min-h-0">
          <ExecutionLogPanel />
        </div>
      )}
    </div>
  );
}
