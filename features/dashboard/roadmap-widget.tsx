"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { useRoadmapStore } from "@/stores/roadmap-store";
import { EmptyState } from "@/components/empty-state";
import { Map, ArrowRight } from "lucide-react";
import { ROUTES } from "@/constants/routes";
import { cleanGeneratedText } from "@/lib/generated-text";

export function RoadmapWidget() {
  const { activeRoadmap } = useRoadmapStore();
  const router = useRouter();

  return (
    <Card className="bg-surface-1 border-hairline">
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-headline text-ink">Learning Roadmap</CardTitle>
        <Button asChild variant="ghost" size="sm" className="text-accent-blue">
          <Link href={ROUTES.ROADMAPS}>
            View All
            <ArrowRight className="ml-2 w-4 h-4" />
          </Link>
        </Button>
      </CardHeader>
      <CardContent>
        {!activeRoadmap ? (
          <EmptyState
            icon={Map}
            title="No active roadmap"
            description="Create a personalized learning roadmap based on your interview results"
            action={{
              label: "Create Roadmap",
              onClick: () => router.push(ROUTES.ROADMAPS),
            }}
          />
        ) : (
          <div className="space-y-4">
            <div>
              <div className="flex items-center justify-between mb-2">
                <h4 className="text-body-sm text-ink font-medium">
                  {cleanGeneratedText(activeRoadmap.title)}
                </h4>
                <span className="text-caption text-ink-muted">
                  {Math.round(activeRoadmap.progress)}%
                </span>
              </div>
              <Progress value={activeRoadmap.progress} className="h-2" />
            </div>

            <div className="space-y-2">
              <h5 className="text-caption text-ink-muted font-medium">
                Next Milestones
              </h5>
              {activeRoadmap.milestones
                .filter((m) => !m.completed)
                .slice(0, 3)
                .map((milestone) => (
                  <div
                    key={milestone.id}
                    className="p-3 bg-surface-2 border border-hairline rounded-md"
                  >
                    <div className="text-body-sm text-ink">{cleanGeneratedText(milestone.title)}</div>
                    <div className="text-caption text-ink-muted mt-1">
                      {milestone.tasks.filter((t) => !t.completed).length} tasks
                      remaining
                    </div>
                  </div>
                ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
