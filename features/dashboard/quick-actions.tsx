import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Video, Dumbbell, Map, FileText } from "lucide-react";
import { ROUTES } from "@/constants/routes";

const actions = [
  {
    icon: Video,
    label: "Start New Interview",
    description: "Begin a full interview simulation",
    href: ROUTES.INTERVIEW,
    variant: "default" as const,
  },
  {
    icon: Dumbbell,
    label: "Practice Arena",
    description: "Quick practice sessions",
    href: ROUTES.PRACTICE_ARENA,
    variant: "outline" as const,
  },
  {
    icon: Map,
    label: "View Roadmap",
    description: "Track your progress",
    href: ROUTES.ROADMAPS,
    variant: "outline" as const,
  },
  {
    icon: FileText,
    label: "Analyze Resume",
    description: "Get ATS feedback",
    href: ROUTES.RESUME_ANALYSIS,
    variant: "outline" as const,
  },
];

export function QuickActions() {
  return (
    <Card className="bg-surface-1 border-hairline">
      <CardContent className="pt-6">
        <h3 className="text-headline text-ink mb-4">Quick Actions</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {actions.map((action, index) => (
            <Button
              key={index}
              asChild
              variant={action.variant}
              className="h-auto flex-col items-start p-4 rounded-lg"
            >
              <Link href={action.href}>
                <action.icon className="w-5 h-5 mb-2" />
                <div className="text-left">
                  <div className="text-body-sm font-medium">{action.label}</div>
                  <div className="text-caption text-ink-muted font-normal">
                    {action.description}
                  </div>
                </div>
              </Link>
            </Button>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
