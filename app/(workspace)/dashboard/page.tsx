"use client";

import dynamic from "next/dynamic";
import { StatsCard } from "@/features/dashboard/stats-card";
import { useAuthStore } from "@/stores/auth-store";
import { apiService } from "@/services/api-service";
import { Video, TrendingUp, Target } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

function ChartLoading() {
  return (
    <div className="rounded-lg border border-hairline bg-surface-1 p-8 text-center text-body text-ink-muted">
      Loading chart...
    </div>
  );
}

const PerformanceChart = dynamic(
  () => import("@/features/dashboard/performance-chart").then((mod) => mod.PerformanceChart),
  { ssr: false, loading: ChartLoading }
);

const QuestionTypeChart = dynamic(
  () => import("@/features/dashboard/question-type-chart").then((mod) => mod.QuestionTypeChart),
  { ssr: false, loading: ChartLoading }
);

const ConfidenceChart = dynamic(
  () => import("@/features/dashboard/confidence-chart").then((mod) => mod.ConfidenceChart),
  { ssr: false, loading: ChartLoading }
);

const SubjectStrengthChart = dynamic(
  () => import("@/features/dashboard/subject-strength-chart").then((mod) => mod.SubjectStrengthChart),
  { ssr: false, loading: ChartLoading }
);

interface DashboardStats {
  total_interviews: number;
  completed_interviews?: number;
  scored_interviews?: number;
  average_score: number;
  average_confidence: number;
  improvement_trend: number;
  interview_change_percent?: number | null;
  score_change_percent?: number | null;
}

type TrendDatum = { label: string; score: number; confidence: number };
type DistributionDatum = { name: string; value: number };
type SubjectDatum = { subject: string; score: number; status: string };
type DashboardOverview = {
  stats: DashboardStats;
  score_trend: any[];
  confidence_trend: any[];
  question_distribution: DistributionDatum[];
  weak_strong_subjects: { subjects: SubjectDatum[]; strong_subjects: SubjectDatum[]; weak_subjects: SubjectDatum[] };
  hydration?: { complete?: boolean; deferred?: boolean };
};

const confidenceLabel = (score: number, scoredInterviews: number) => {
  if (scoredInterviews === 0) return "No score yet";
  if (score >= 70) return "High";
  if (score >= 50) return "Medium";
  return "Low";
};

const trendFor = (change?: number | null) => {
  if (change === undefined || change === null || change === 0) return "neutral";
  return change > 0 ? "up" : "down";
};

const isDashboardTimeout = (error: unknown) =>
  error instanceof Error && error.message.toLowerCase().includes("timed out");

const dashboardRetryDelaysMs = [0, 1200, 2500, 4000];

const sleep = (delayMs: number) => new Promise((resolve) => setTimeout(resolve, delayMs));

const hasDashboardData = (overview: DashboardOverview) =>
  (overview.stats?.total_interviews ?? 0) > 0 ||
  (overview.stats?.scored_interviews ?? 0) > 0 ||
  overview.score_trend.length > 0 ||
  overview.confidence_trend.length > 0 ||
  overview.question_distribution.length > 0 ||
  overview.weak_strong_subjects.subjects.length > 0;

const shouldRetryOverview = (overview: DashboardOverview) =>
  overview.hydration?.complete === false && !hasDashboardData(overview);

const timeGreeting = () => {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
};

export default function DashboardPage() {
  const { user } = useAuthStore();
  const [overview, setOverview] = useState<DashboardOverview | null>(null);
  const [isDashboardLoading, setIsDashboardLoading] = useState(true);
  const [dashboardError, setDashboardError] = useState("");
  const greeting = useMemo(() => timeGreeting(), []);

  useEffect(() => {
    if (!user?.id) return;
    let mounted = true;
    setIsDashboardLoading(true);
    setDashboardError("");

    const loadDashboard = async () => {
      let lastError: unknown = null;
      for (let attempt = 0; attempt < dashboardRetryDelaysMs.length; attempt += 1) {
        const delayMs = dashboardRetryDelaysMs[attempt];
        if (delayMs > 0) {
          await sleep(delayMs);
        }
        if (!mounted) return;

        try {
          const nextOverview = await apiService.request<DashboardOverview>("/api/dashboard/overview", {
            forceRefresh: true,
            timeoutMs: 25_000,
          });
          if (!mounted) return;
          if (shouldRetryOverview(nextOverview) && attempt < dashboardRetryDelaysMs.length - 1) {
            continue;
          }
          setOverview(nextOverview);
          setDashboardError(
            nextOverview.hydration?.complete === false
              ? "Dashboard data is still syncing from the backend. Refresh is not required."
              : ""
          );
          return;
        } catch (error) {
          lastError = error;
          if (attempt < dashboardRetryDelaysMs.length - 1) {
            continue;
          }
        }
      }

      if (!mounted) return;
      setDashboardError(
        isDashboardTimeout(lastError)
          ? "Dashboard data is taking longer than expected to sync. Please try again in a moment."
          : lastError instanceof Error
            ? lastError.message
            : "Unable to load dashboard data."
      );
    };

    loadDashboard().finally(() => {
      if (mounted) setIsDashboardLoading(false);
    });

    return () => {
      mounted = false;
    };
  }, [user?.id]);

  const trendData = useMemo<TrendDatum[]>(
    () =>
      (overview?.score_trend || []).map((point) => ({
        label: point.label,
        score: Number(point.overall_score || 0),
        confidence:
          Number(
            overview?.confidence_trend.find((item) => item.label === point.label)?.confidence ??
              point.confidence ??
              0
          ) || 0,
      })),
    [overview]
  );

  const distributionData = overview?.question_distribution || [];
  const subjectData = overview?.weak_strong_subjects.subjects || [];

  const stats = useMemo(() => {
    const apiStats = overview?.stats;
    const totalInterviews = apiStats?.total_interviews ?? 0;
    const scoredInterviews = apiStats?.scored_interviews ?? 0;
    const averageScore = apiStats?.average_score ?? 0;
    const averageConfidence = apiStats?.average_confidence ?? 0;

    return {
      totalInterviews,
      averageScore: Math.round(averageScore),
      averageScoreLabel: scoredInterviews === 0 ? "No score yet" : `${Math.round(averageScore)}%`,
      confidence: confidenceLabel(averageConfidence, scoredInterviews),
      interviewChange: apiStats?.interview_change_percent,
      scoreChange: scoredInterviews > 0 ? apiStats?.score_change_percent : undefined,
    };
  }, [overview]);

  return (
    
    <div className="space-y-8">
      <div>
        <h1 className="text-display-lg text-ink mb-2">
          {greeting}, {user?.name || "User"}
        </h1>
        <p className="text-body text-ink-muted">
          Here&apos;s your interview preparation analytics
        </p>
      </div>

      {isDashboardLoading && !overview && (
        <div className="rounded-lg border border-hairline bg-surface-1 p-4 text-body-sm text-ink-muted">
          Syncing dashboard with your backend interview history...
        </div>
      )}

      {dashboardError && (
        <div className="rounded-lg border border-gradient-coral/40 bg-surface-1 p-4 text-body-sm text-gradient-coral">
          Dashboard data could not be loaded from the backend: {dashboardError}
        </div>
      )}

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <StatsCard
          title="Total Interviews"
          value={stats.totalInterviews}
          change={stats.interviewChange}
          icon={Video}
          trend={trendFor(stats.interviewChange)}
        />
        <StatsCard
          title="Average Score"
          value={stats.averageScoreLabel}
          change={stats.scoreChange}
          icon={TrendingUp}
          trend={trendFor(stats.scoreChange)}
        />
        <StatsCard
          title="Confidence Level"
          value={stats.confidence}
          icon={Target}
        />
      </div>

      {/* Charts Row 1 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <PerformanceChart data={trendData} />
        <ConfidenceChart data={trendData} />
      </div>

      {/* Charts Row 2 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <QuestionTypeChart data={distributionData} />
        <SubjectStrengthChart data={subjectData} />
      </div>
    </div>
  
  );
}
