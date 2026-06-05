"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useReportStore } from "@/stores/report-store";
import { EmptyState } from "@/components/empty-state";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { apiService } from "@/services/api-service";
import { AlertTriangle, CalendarDays, CheckCircle2, FileText, ListChecks, TrendingUp } from "lucide-react";
import { ROUTES } from "@/constants/routes";
import type { Report } from "@/types";
import { cleanGeneratedText } from "@/lib/generated-text";
import { cn } from "@/lib/utils";

function formatDate(value: Date | string) {
  return new Date(value).toLocaleDateString("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function reportText(value: unknown, fallback = "") {
  return cleanGeneratedText(value, fallback);
}

export default function ReportsPage() {
  const { reports, setReports, isLoading, setLoading } = useReportStore();
  const router = useRouter();
  const [error, setError] = useState("");
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);
  const selectedReport = reports.find((report) => report.id === selectedReportId) || reports[0];

  useEffect(() => {
    let isMounted = true;

    async function loadReports() {
      setError("");
      setLoading(true);
      try {
        const response = await apiService.request<Report[]>("/api/reports");
        if (isMounted) {
          setReports(response);
        }
      } catch (loadError) {
        if (isMounted) {
          setError(loadError instanceof Error ? loadError.message : "Unable to load reports.");
        }
      } finally {
        if (isMounted) {
          setLoading(false);
        }
      }
    }

    loadReports();

    return () => {
      isMounted = false;
    };
  }, [setLoading, setReports]);

  useEffect(() => {
    if (!selectedReportId && reports.length > 0) {
      setSelectedReportId(reports[0].id);
    }
  }, [reports, selectedReportId]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-display-lg text-ink mb-2">Interview Reports</h1>
        <p className="text-body text-ink-muted">
          View detailed analytics and feedback from your interviews
        </p>
      </div>

      {error && (
        <Card className="border-hairline bg-surface-1">
          <CardContent className="py-4 text-body-sm text-gradient-coral">{error}</CardContent>
        </Card>
      )}

      {isLoading ? (
        <Card className="border-hairline bg-surface-1">
          <CardContent className="py-10 text-center text-body text-ink-muted">Loading reports...</CardContent>
        </Card>
      ) : reports.length === 0 ? (
        <EmptyState
          icon={FileText}
          title="No reports yet"
          description="Complete an interview to generate your first detailed report with AI-powered insights"
          action={{
            label: "Start Interview",
            onClick: () => router.push(ROUTES.INTERVIEW),
          }}
        />
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 2xl:grid-cols-3">
            {reports.map((report) => (
              <button
                key={report.id}
                onClick={() => setSelectedReportId(report.id)}
                className={cn(
                  "min-w-0 overflow-hidden rounded-lg border border-hairline bg-surface-1 p-5 text-left transition-colors hover:border-accent-blue/60",
                  selectedReport?.id === report.id && "border-accent-blue"
                )}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-headline text-ink">{Math.round(report.overallScore)}/100</p>
                    <p className="mt-1 flex items-center gap-2 text-caption text-ink-muted">
                      <CalendarDays className="h-3.5 w-3.5" />
                      {formatDate(report.createdAt)}
                    </p>
                  </div>
                  <TrendingUp className="h-5 w-5 text-accent-blue" />
                </div>
                <p className="mt-4 line-clamp-3 text-body-sm text-ink-muted">
                  {reportText(report.executiveSummary || report.aiFeedback)}
                </p>
                <div className="mt-4 flex flex-wrap gap-2">
                  {report.weaknesses.slice(0, 3).map((weakness, index) => (
                    <span
                      key={`${weakness}-${index}`}
                      className="min-w-0 max-w-full overflow-hidden text-ellipsis whitespace-nowrap rounded-sm border border-hairline px-2 py-0.5 text-caption text-ink-muted"
                    >
                      {reportText(weakness)}
                    </span>
                  ))}
                </div>
              </button>
            ))}
          </div>

          {selectedReport && (
            <div className="space-y-6">
              <Card className="border-hairline bg-surface-1">
                <CardHeader>
                  <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                    <div>
                      <CardTitle className="text-headline text-ink">Detailed Interview Analysis</CardTitle>
                      <p className="mt-1 text-body-sm text-ink-muted">
                        Generated {formatDate(selectedReport.createdAt)}
                      </p>
                    </div>
                    <div className="rounded-lg border border-hairline bg-surface-2 px-4 py-3 text-right">
                      <p className="text-caption text-ink-muted">Overall score</p>
                      <p className="text-display-sm text-ink">{Math.round(selectedReport.overallScore)}/100</p>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-6">
                  <p className="text-body leading-relaxed text-ink-muted">
                    {reportText(selectedReport.executiveSummary || selectedReport.aiFeedback)}
                  </p>

                  <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                    <div className="rounded-lg border border-hairline bg-surface-2 p-4">
                      <div className="mb-3 flex items-center gap-2 text-ink">
                        <CheckCircle2 className="h-4 w-4 text-semantic-success" />
                        <h3 className="text-body font-semibold">Strengths</h3>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {selectedReport.strengths.map((strength, index) => (
                          <span
                            key={`${strength}-${index}`}
                            className="min-w-0 max-w-full overflow-hidden text-ellipsis whitespace-nowrap rounded-sm bg-primary px-2 py-0.5 text-caption font-medium text-on-primary"
                          >
                            {reportText(strength)}
                          </span>
                        ))}
                      </div>
                    </div>

                    <div className="rounded-lg border border-hairline bg-surface-2 p-4">
                      <div className="mb-3 flex items-center gap-2 text-ink">
                        <AlertTriangle className="h-4 w-4 text-gradient-coral" />
                        <h3 className="text-body font-semibold">Weak Areas</h3>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {selectedReport.weaknesses.map((weakness, index) => (
                          <span
                            key={`${weakness}-${index}`}
                            className="min-w-0 max-w-full overflow-hidden text-ellipsis whitespace-nowrap rounded-sm border border-hairline px-2 py-0.5 text-caption text-ink-muted"
                          >
                            {reportText(weakness)}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>

                  {(selectedReport.communicationSummary || selectedReport.proctorSummary) && (
                    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                      <div className="rounded-lg border border-hairline bg-surface-2 p-4">
                        <h3 className="mb-3 text-body font-semibold text-ink">Communication Confidence</h3>
                        {(["technical", "hr"] as const).map((round) => {
                          const summary = selectedReport.communicationSummary?.[round];
                          if (!summary) return null;
                          return (
                            <div key={round} className="mb-3 last:mb-0">
                              <p className="text-caption uppercase text-ink-muted">{round}</p>
                              <p className="mt-1 text-body-sm text-ink-muted">
                                {reportText(summary.dominantLabel, "not captured")} confidence,{" "}
                                {Math.round(Number(summary.averageConfidence || 0) * 100)}% recognition confidence,{" "}
                                {Math.round(Number(summary.averageWordsPerMinute || 0))} wpm,{" "}
                                {Number(summary.longPauseCount || 0)} long pauses.
                              </p>
                            </div>
                          );
                        })}
                      </div>

                      <div className="rounded-lg border border-hairline bg-surface-2 p-4">
                        <h3 className="mb-3 text-body font-semibold text-ink">Proctor Summary</h3>
                        {(["technical", "hr"] as const).map((round) => {
                          const summary = selectedReport.proctorSummary?.[round];
                          if (!summary) return null;
                          return (
                            <div key={round} className="mb-3 last:mb-0">
                              <p className="text-caption uppercase text-ink-muted">{round}</p>
                              <p className="mt-1 text-body-sm text-ink-muted">
                                {Number(summary.eventCount || 0)} event{Number(summary.eventCount || 0) === 1 ? "" : "s"} recorded.
                              </p>
                              {Array.isArray(summary.messages) && summary.messages.length > 0 && (
                                <p className="mt-1 line-clamp-2 text-caption text-ink-muted">
                                  {summary.messages.map((message: string) => reportText(message)).join(" | ")}
                                </p>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  <div className="space-y-4">
                    {selectedReport.sections.map((section) => (
                      <div key={section.name} className="rounded-lg border border-hairline bg-surface-2 p-4">
                        <div className="mb-3 flex items-center justify-between gap-3">
                          <div>
                            <h3 className="text-body font-semibold text-ink">{reportText(section.name)}</h3>
                            <p className="text-body-sm text-ink-muted">{reportText(section.feedback)}</p>
                          </div>
                          <span className="shrink-0 text-body font-semibold text-ink">
                            {Math.round(section.score)}/100
                          </span>
                        </div>
                        <Progress value={section.score} />
                        {Array.isArray(section.details?.actionItems) && section.details.actionItems.length > 0 && (
                          <div className="mt-4 space-y-2">
                            {section.details.actionItems.slice(0, 4).map((item: string, index: number) => (
                              <div key={`${item}-${index}`} className="flex gap-2 text-body-sm text-ink-muted">
                                <ListChecks className="mt-0.5 h-4 w-4 shrink-0 text-accent-blue" />
                                <span>{reportText(item)}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>

              <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
                <Card className="border-hairline bg-surface-1">
                  <CardHeader>
                    <CardTitle className="text-headline text-ink">What Went Wrong</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {(selectedReport.whatWentWrong || []).map((item, index) => (
                      <div key={`${item}-${index}`} className="flex gap-2 text-body-sm text-ink-muted">
                        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-gradient-coral" />
                        <span>{reportText(item)}</span>
                      </div>
                    ))}
                  </CardContent>
                </Card>

                <Card className="border-hairline bg-surface-1">
                  <CardHeader>
                    <CardTitle className="text-headline text-ink">Next Time</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {(selectedReport.nextTimeSuggestions || []).map((item, index) => (
                      <div key={`${item}-${index}`} className="flex gap-2 text-body-sm text-ink-muted">
                        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-semantic-success" />
                        <span>{reportText(item)}</span>
                      </div>
                    ))}
                  </CardContent>
                </Card>
              </div>

              {selectedReport.actionPlan && selectedReport.actionPlan.length > 0 && (
                <Card className="border-hairline bg-surface-1">
                  <CardHeader>
                    <CardTitle className="text-headline text-ink">Action Plan</CardTitle>
                  </CardHeader>
                  <CardContent className="grid grid-cols-1 gap-3 md:grid-cols-3">
                    {selectedReport.actionPlan.map((item) => (
                      <div key={item.id || item.title} className="rounded-lg border border-hairline bg-surface-2 p-4">
                        <Badge variant="outline" className="mb-3 border-hairline text-ink-muted">
                          {reportText(item.priority)}
                        </Badge>
                        <h3 className="text-body font-semibold text-ink">{reportText(item.title)}</h3>
                        <p className="mt-2 text-body-sm text-ink-muted">{reportText(item.description)}</p>
                      </div>
                    ))}
                  </CardContent>
                </Card>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
