"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  FileText,
  Info,
  Search,
  Sparkles,
  Upload,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { apiService } from "@/services/api-service";
import { jobRoleGroups } from "@/constants/job-roles";
import { cleanGeneratedText } from "@/lib/generated-text";
import { cn } from "@/lib/utils";

type RewriteSuggestion = {
  type?: "line" | "paragraph" | "section" | string;
  currentText: string;
  suggestedText: string;
  reason: string;
};

type SectionAnalysis = {
  key: string;
  name: string;
  score: number;
  status: string;
  currentText: string;
  strengths: string[];
  improvements: string[];
  basis: string[];
  rewriteSuggestions: RewriteSuggestion[];
};

type ResumeAnalysis = {
  fileName?: string;
  targetRole?: string | null;
  roleSpecific?: boolean;
  atsScore: number;
  keywordScore: number;
  overallResumeScore?: number;
  scoreBasis?: Record<string, string>;
  marketSummary?: string;
  keywords?: {
    expected?: string[];
    found?: string[];
    missing?: string[];
    coverage?: number;
    explanation?: string;
  };
  sectionAnalyses?: SectionAnalysis[];
  missingInformation?: Array<{ label: string; severity: string; reason: string }>;
  missingSkills?: string[];
};

const roleOptions = jobRoleGroups.map((group) => ({
  group: group.group,
  roles: [...group.roles],
}));

const fallbackScoreBasis = {
  atsScore:
    "ATS score combines section completeness, parse-friendly structure, dates/contact signals, action verbs, and measurable evidence.",
  keywordScore:
    "Keyword coverage checks whether the resume clearly names relevant skills. It is not a judgment that you must learn every missing skill.",
  overallResumeScore: "Overall score combines resume structure and keyword coverage.",
};

function text(value: unknown, fallback = "") {
  return cleanGeneratedText(value, fallback);
}

function scoreTone(score: number) {
  if (score >= 82) return "text-semantic-success";
  if (score >= 65) return "text-accent-blue";
  return "text-gradient-coral";
}

function hasActionableImprovement(section: SectionAnalysis) {
  return (section.improvements || []).some((item) => {
    const lower = item.toLowerCase();
    return !["pretty good", "no change", "no rewrite", "clear and complete"].some((phrase) => lower.includes(phrase));
  });
}

export default function ResumeAnalysisPage() {
  const [file, setFile] = useState<File | null>(null);
  const [targetRole, setTargetRole] = useState("");
  const [roleSearch, setRoleSearch] = useState("");
  const [roleOpen, setRoleOpen] = useState(false);
  const [analysis, setAnalysis] = useState<ResumeAnalysis | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const roleRef = useRef<HTMLDivElement>(null);

  const filteredRoleGroups = useMemo(() => {
    const query = roleSearch.trim().toLowerCase();
    if (!query) return roleOptions;
    return roleOptions
      .map((group) => ({
        ...group,
        roles: group.roles.filter((role) => role.toLowerCase().includes(query)),
      }))
      .filter((group) => group.roles.length > 0);
  }, [roleSearch]);

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      if (!roleRef.current?.contains(event.target as Node)) {
        setRoleOpen(false);
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, []);

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = event.target.files?.[0];
    if (selectedFile) {
      setFile(selectedFile);
      setAnalysis(null);
    }
  };

  const handleAnalyze = async () => {
    if (!file) return;
    setIsAnalyzing(true);
    const payload = new FormData();
    payload.append("file", file);
    if (targetRole.trim()) {
      payload.append("target_role", targetRole.trim());
    }

    try {
      const result = await apiService.request<ResumeAnalysis>("/api/resume/analyze", {
        method: "POST",
        body: payload,
      });
      setAnalysis(result);
    } catch (error) {
      alert(error instanceof Error ? error.message : "Resume analysis failed");
    } finally {
      setIsAnalyzing(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="mb-2 text-display-lg text-ink">Resume Analysis</h1>
        <p className="text-body text-ink-muted">
          Upload a resume and optionally select a target role for role-specific keyword and market-fit analysis.
        </p>
      </div>

      <Card className="border-hairline bg-surface-1">
        <CardContent className="space-y-5 pt-6">
          <div ref={roleRef} className="relative">
            <label className="mb-2 block text-body-sm font-medium text-ink">Target Job Role</label>
            <button
              type="button"
              onClick={() => setRoleOpen((open) => !open)}
              className="flex h-12 w-full items-center justify-between rounded-md border border-hairline bg-surface-2 px-4 text-left text-body text-ink"
            >
              <span className={cn("truncate", !targetRole && "text-ink-muted")}>
                {targetRole || "Analyze generally, or choose a role..."}
              </span>
              <ChevronDown className="h-4 w-4 shrink-0 text-ink-muted" />
            </button>

            {roleOpen && (
              <div className="absolute z-30 mt-2 max-h-96 w-full overflow-hidden rounded-lg border border-hairline bg-surface-1 shadow-2xl">
                <div className="border-b border-hairline p-3">
                  <div className="flex h-11 items-center gap-2 rounded-md border border-hairline bg-surface-2 px-3">
                    <Search className="h-4 w-4 text-ink-muted" />
                    <input
                      value={roleSearch}
                      onChange={(event) => setRoleSearch(event.target.value)}
                      placeholder="Search technical or non-technical roles..."
                      className="min-w-0 flex-1 bg-transparent text-body-sm text-ink outline-none placeholder:text-ink-muted"
                      autoFocus
                    />
                  </div>
                </div>
                <div className="max-h-72 overflow-y-auto p-2">
                  {filteredRoleGroups.length === 0 ? (
                    <button
                      type="button"
                      onClick={() => {
                        setTargetRole(roleSearch.trim());
                        setAnalysis(null);
                        setRoleOpen(false);
                      }}
                      className="w-full rounded-md px-3 py-2 text-left text-body-sm text-ink hover:bg-surface-2"
                    >
                      Use "{roleSearch.trim()}"
                    </button>
                  ) : (
                    filteredRoleGroups.map((group) => (
                      <div key={group.group} className="py-1">
                        <p className="px-3 py-2 text-micro uppercase tracking-wide text-ink-muted">{group.group}</p>
                        {group.roles.map((role) => {
                          const selected = targetRole === role;
                          return (
                            <button
                              key={role}
                              type="button"
                              onClick={() => {
                                setTargetRole(role);
                                setAnalysis(null);
                                setRoleSearch("");
                                setRoleOpen(false);
                              }}
                              className="flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-body-sm text-ink hover:bg-surface-2"
                            >
                              <span>{role}</span>
                              {selected && <CheckCircle2 className="h-4 w-4 text-accent-blue" />}
                            </button>
                          );
                        })}
                      </div>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>

          <div
            onClick={() => fileInputRef.current?.click()}
            className={cn(
              "cursor-pointer rounded-lg border-2 border-dashed p-10 text-center transition-colors",
              file ? "border-primary bg-primary/5" : "border-hairline hover:border-accent-blue/50"
            )}
          >
            <div
              className={cn(
                "mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full transition-colors",
                file ? "bg-primary/20" : "bg-surface-2"
              )}
            >
              <Upload className={cn("h-8 w-8", file ? "text-primary" : "text-accent-blue")} />
            </div>
            <h3 className="mb-2 text-headline text-ink">{file ? file.name : "Upload Your Resume"}</h3>
            <p className="mb-6 text-body text-ink-muted">
              {file ? `${(file.size / (1024 * 1024)).toFixed(2)} MB` : "PDF, DOC, or DOCX up to 10MB"}
            </p>
            <Button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                if (file) {
                  handleAnalyze();
                } else {
                  fileInputRef.current?.click();
                }
              }}
              disabled={isAnalyzing}
              className="rounded-pill bg-primary text-on-primary"
            >
              <FileText className="mr-2 h-4 w-4" />
              {isAnalyzing ? "Analyzing..." : file ? "Analyze Now" : "Choose File"}
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              accept=".pdf,.doc,.docx"
              onChange={handleFileChange}
            />
          </div>
        </CardContent>
      </Card>

      {analysis && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
            {[
              ["Overall", analysis.overallResumeScore ?? analysis.atsScore],
              ["ATS / Structure", analysis.atsScore],
              ["Keyword Coverage", analysis.keywordScore],
              ["Target Role", analysis.targetRole || targetRole || "General"],
            ].map(([label, value]) => (
              <Card key={label} className="border-hairline bg-surface-1">
                <CardContent className="p-4">
                  <p className="text-caption text-ink-muted">{label}</p>
                  <p className="mt-2 text-display-sm text-ink">
                    {typeof value === "number" ? `${Math.round(value)}%` : text(value)}
                  </p>
                </CardContent>
              </Card>
            ))}
          </div>

          <Card className="border-hairline bg-surface-1">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-headline text-ink">
                <Info className="h-5 w-5 text-accent-blue" />
                How The Scores Were Calculated
              </CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-1 gap-3 md:grid-cols-3">
              {Object.entries(analysis.scoreBasis || fallbackScoreBasis).map(([label, description]) => (
                <div key={label} className="rounded-lg border border-hairline bg-surface-2 p-4">
                  <p className="text-body-sm font-semibold capitalize text-ink">{label.replace(/([A-Z])/g, " $1")}</p>
                  <p className="mt-2 text-body-sm text-ink-muted">{text(description)}</p>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card className="border-hairline bg-surface-1">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-headline text-ink">
                <Sparkles className="h-5 w-5 text-accent-blue" />
                Market Fit Summary
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-body leading-relaxed text-ink-muted">
                {text(
                  analysis.marketSummary,
                  targetRole
                    ? `Re-run the analysis to generate a role-specific market summary for ${targetRole}.`
                    : "Select a target role and re-run analysis to generate role-specific market expectations."
                )}
              </p>
            </CardContent>
          </Card>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <Card className="border-hairline bg-surface-1">
              <CardHeader>
                <CardTitle className="text-headline text-ink">Missing Information</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {(analysis.missingInformation || []).length === 0 ? (
                  <div className="flex gap-2 text-body-sm text-ink-muted">
                    <CheckCircle2 className="mt-0.5 h-4 w-4 text-semantic-success" />
                    <span>General resume information looks complete.</span>
                  </div>
                ) : (
                  analysis.missingInformation?.map((item, index) => (
                    <div key={`${item.label}-${index}`} className="flex gap-2 text-body-sm text-ink-muted">
                      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-gradient-coral" />
                      <span>
                        <span className="font-medium text-ink">{text(item.label)}:</span> {text(item.reason)}
                      </span>
                    </div>
                  ))
                )}
              </CardContent>
            </Card>

            <Card className="border-hairline bg-surface-1">
              <CardHeader>
                <CardTitle className="text-headline text-ink">Role Keyword Coverage</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <p className="text-body-sm text-ink-muted">{text(analysis.keywords?.explanation)}</p>
                <div>
                  <p className="mb-2 text-caption text-ink-muted">Found</p>
                  <div className="flex flex-wrap gap-2">
                    {(analysis.keywords?.found || []).length > 0 ? (
                      analysis.keywords?.found?.map((keyword, index) => (
                        <Badge key={`${keyword}-${index}`} className="bg-primary text-on-primary">
                          {text(keyword)}
                        </Badge>
                      ))
                    ) : (
                      <span className="text-body-sm text-ink-muted">No matching role keywords detected yet.</span>
                    )}
                  </div>
                </div>
                <div>
                  <p className="mb-2 text-caption text-ink-muted">
                    {analysis.roleSpecific ? "Role-specific gaps" : "Role-specific gaps"}
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {analysis.roleSpecific && (analysis.keywords?.missing || []).length > 0 ? (
                      analysis.keywords?.missing?.slice(0, 10).map((keyword, index) => (
                        <Badge key={`${keyword}-${index}`} variant="outline" className="border-hairline text-ink-muted">
                          {text(keyword)}
                        </Badge>
                      ))
                    ) : (
                      <span className="text-body-sm text-ink-muted">
                        {analysis.roleSpecific
                          ? "No major role keyword gap detected."
                          : "Select a target role to check role-specific skill gaps."}
                      </span>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          <Card className="border-hairline bg-surface-1">
            <CardHeader>
              <CardTitle className="text-headline text-ink">Section-Wise Detailed Report</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {(analysis.sectionAnalyses || []).length === 0 && (
                <div className="rounded-lg border border-hairline bg-surface-2 p-4 text-body-sm text-ink-muted">
                  Re-run the analysis to generate the detailed section-wise report with current text and rewrite suggestions.
                </div>
              )}
              {(analysis.sectionAnalyses || []).map((section) => (
                <div key={section.key} className="rounded-lg border border-hairline bg-surface-2 p-4">
                  <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                    <div>
                      <h3 className="text-body font-semibold text-ink">{text(section.name)}</h3>
                      <p className={cn("mt-1 text-body-sm font-medium", scoreTone(section.score))}>
                        {Math.round(section.score)}% - {text(section.status)}
                      </p>
                    </div>
                    <div className="w-full md:w-56">
                      <Progress value={section.score} />
                    </div>
                  </div>

                  <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                    <div>
                      <p className="mb-2 text-caption text-ink-muted">Current Text</p>
                      <pre className="max-h-56 overflow-y-auto whitespace-pre-wrap rounded-md border border-hairline bg-surface-1 p-3 text-caption leading-5 text-ink-muted">
                        {section.currentText ? text(section.currentText) : "No clear text detected for this section."}
                      </pre>
                    </div>
                    <div className="space-y-3">
                      <div>
                        <p className="mb-2 text-caption text-ink-muted">Basis</p>
                        <div className="space-y-1">
                          {section.basis.map((item, index) => (
                            <p key={`${item}-${index}`} className="text-body-sm text-ink-muted">
                              {text(item)}
                            </p>
                          ))}
                        </div>
                      </div>
                      <div>
                        <p className="mb-2 text-caption text-ink-muted">What To Improve</p>
                        <div className="space-y-2">
                          {section.improvements.map((item, index) => (
                            <div key={`${item}-${index}`} className="flex gap-2 text-body-sm text-ink-muted">
                              {item.toLowerCase().includes("pretty good") ? (
                                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-semantic-success" />
                              ) : (
                                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-gradient-coral" />
                              )}
                              <span>{text(item)}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="mt-4 space-y-3">
                    <p className="text-caption text-ink-muted">Suggested Text</p>
                    {section.rewriteSuggestions.length === 0 ? (
                      <div className="rounded-md border border-hairline bg-surface-1 p-3 text-body-sm text-ink-muted">
                        {hasActionableImprovement(section)
                          ? "No exact rewrite was returned for this section; use the improvement notes above."
                          : "No rewrite needed for this section right now."}
                      </div>
                    ) : (
                      section.rewriteSuggestions.map((suggestion, index) => (
                        <div key={`${suggestion.currentText}-${index}`} className="rounded-md border border-hairline bg-surface-1 p-3">
                          <p className="text-caption text-ink-muted">
                            Current {suggestion.type === "paragraph" ? "Paragraph" : suggestion.type === "section" ? "Section" : "Line"}
                          </p>
                          <p className="mt-1 whitespace-pre-wrap text-body-sm text-ink-muted">{text(suggestion.currentText)}</p>
                          <p className="mt-3 text-caption text-ink-muted">
                            Suggested {suggestion.type === "paragraph" ? "Paragraph" : suggestion.type === "section" ? "Section" : "Line"}
                          </p>
                          <p className="mt-1 whitespace-pre-wrap text-body-sm text-ink">{text(suggestion.suggestedText)}</p>
                          <p className="mt-2 text-caption text-ink-muted">{text(suggestion.reason)}</p>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
