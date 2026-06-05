"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useReportStore } from "@/stores/report-store";
import { EmptyState } from "@/components/empty-state";
import { FileText, ArrowRight } from "lucide-react";
import { ROUTES } from "@/constants/routes";
import { cleanGeneratedText } from "@/lib/generated-text";
import { format } from "date-fns";

export function RecentReports() {
  const { reports } = useReportStore();
  const router = useRouter();
  const recentReports = reports.slice(0, 5);

  return (
    <Card className="bg-surface-1 border-hairline">
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-headline text-ink">Recent Reports</CardTitle>
        <Button asChild variant="ghost" size="sm" className="text-accent-blue">
          <Link href={ROUTES.REPORTS}>
            View All
            <ArrowRight className="ml-2 w-4 h-4" />
          </Link>
        </Button>
      </CardHeader>
      <CardContent>
        {recentReports.length === 0 ? (
          <EmptyState
            icon={FileText}
            title="No reports yet"
            description="Complete an interview to see your first report here"
            action={{
              label: "Start Interview",
              onClick: () => router.push(ROUTES.INTERVIEW),
            }}
          />
        ) : (
          <div className="space-y-3">
            {recentReports.map((report) => (
              <Link
                key={report.id}
                href={`${ROUTES.REPORTS}/${report.id}`}
                className="block p-4 bg-surface-2 border border-hairline rounded-lg hover:border-accent-blue/50 transition-colors"
              >
                <div className="flex items-start justify-between mb-2">
                  <div className="flex-1">
                    <div className="text-body-sm text-ink font-medium mb-1">
                      Interview Report
                    </div>
                    <div className="text-caption text-ink-muted">
                      {format(new Date(report.createdAt), "MMM dd, yyyy")}
                    </div>
                  </div>
                  <Badge
                    variant="outline"
                    className={
                      report.overallScore >= 80
                        ? "border-semantic-success text-semantic-success"
                        : report.overallScore >= 60
                        ? "border-accent-blue text-accent-blue"
                        : "border-gradient-orange text-gradient-orange"
                    }
                  >
                    {report.overallScore}%
                  </Badge>
                </div>
                <div className="flex items-center gap-2">
                  {report.sections.slice(0, 3).map((section, i) => (
                    <span key={i} className="text-micro text-ink-muted">
                      {cleanGeneratedText(section.name)}: {section.score}/{section.maxScore}
                    </span>
                  ))}
                </div>
              </Link>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
