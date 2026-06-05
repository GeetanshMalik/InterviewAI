import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

interface StatsCardProps {
  title: string;
  value: string | number;
  change?: number | null;
  changeLabel?: string;
  icon: LucideIcon;
  trend?: "up" | "down" | "neutral";
}

export function StatsCard({
  title,
  value,
  change,
  changeLabel,
  icon: Icon,
  trend = "neutral",
}: StatsCardProps) {
  const hasChange = change !== undefined || changeLabel;
  const label =
    changeLabel ||
    (change === null
      ? "No prior month"
      : `${change && change > 0 ? "+" : ""}${change ?? 0}% from last month`);

  return (
    <Card className="bg-surface-1 border-hairline hover:border-accent-blue/50 transition-colors">
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <span className="text-caption text-ink-muted font-medium">{title}</span>
        <Icon className="w-5 h-5 text-accent-blue" />
      </CardHeader>
      <CardContent>
        <div className="text-display-md text-ink mb-1">{value}</div>
        {hasChange && (
          <div
            className={cn(
              "text-body-sm flex items-center gap-1",
              trend === "up" && "text-semantic-success",
              trend === "down" && "text-gradient-orange",
              trend === "neutral" && "text-ink-muted"
            )}
          >
            {label}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
