import { LandingLayout } from "@/layouts/landing-layout";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CheckCircle2, Circle } from "lucide-react";

const roadmapItems = [
  {
    quarter: "Now",
    status: "completed",
    items: [
      "LangGraph-backed multi-agent interview generation",
      "Backend-controlled adaptive Technical and HR runtime",
      "Report, roadmap, memory, and evaluation lifecycle graph",
      "Completed-interview analytics and synced score/confidence trends",
    ],
  },
  {
    quarter: "Next",
    status: "in-progress",
    items: [
      "Deeper production persistence and account controls",
      "More transparent agent activity and workflow diagnostics",
      "Expanded resume-aware practice recommendations",
      "Stronger media and runtime reliability for live interview rounds",
    ],
  },
  {
    quarter: "Later",
    status: "planned",
    items: [
      "Team interview workspaces",
      "Calendar and hiring-platform integrations",
      "Mobile-first interview practice",
      "Admin controls for organization-level preparation programs",
    ],
  },
];

export default function RoadmapPage() {
  return (
    <LandingLayout>
      <div className="py-section">
        <div className="container mx-auto px-4">
          <div className="text-center mb-16">
            <h1 className="text-display-lg text-ink mb-4">Product Roadmap</h1>
            <p className="text-subhead text-ink-muted max-w-2xl mx-auto">
              The current path for turning InterviewAI into a real autonomous interview operating system
            </p>
          </div>

          <div className="max-w-4xl mx-auto space-y-6">
            {roadmapItems.map((item, index) => (
              <Card key={index} className="bg-surface-1 border-hairline">
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-headline text-ink">{item.quarter}</CardTitle>
                    <span
                      className={`text-caption px-3 py-1 rounded-pill ${
                        item.status === "completed"
                          ? "bg-semantic-success/20 text-semantic-success"
                          : item.status === "in-progress"
                          ? "bg-accent-blue/20 text-accent-blue"
                          : "bg-surface-2 text-ink-muted"
                      }`}
                    >
                      {item.status === "completed"
                        ? "Completed"
                        : item.status === "in-progress"
                        ? "In Progress"
                        : "Planned"}
                    </span>
                  </div>
                </CardHeader>
                <CardContent>
                  <ul className="space-y-3">
                    {item.items.map((feature, i) => (
                      <li key={i} className="flex items-center gap-3">
                        {item.status === "completed" ? (
                          <CheckCircle2 className="w-5 h-5 text-semantic-success flex-shrink-0" />
                        ) : (
                          <Circle className="w-5 h-5 text-ink-muted flex-shrink-0" />
                        )}
                        <span className="text-body text-ink">{feature}</span>
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </div>
    </LandingLayout>
  );
}
