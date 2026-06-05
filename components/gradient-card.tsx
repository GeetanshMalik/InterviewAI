import { cn } from "@/lib/utils";
import { ReactNode } from "react";

interface GradientCardProps {
  children: ReactNode;
  variant?: "violet" | "magenta" | "orange" | "coral";
  className?: string;
}

export function GradientCard({
  children,
  variant = "violet",
  className,
}: GradientCardProps) {
  const gradients = {
    violet: "bg-gradient-to-br from-gradient-violet to-gradient-magenta",
    magenta: "bg-gradient-to-br from-gradient-magenta to-gradient-coral",
    orange: "bg-gradient-to-br from-gradient-orange to-gradient-coral",
    coral: "bg-gradient-to-br from-gradient-coral to-gradient-magenta",
  };

  return (
    <div
      className={cn(
        "relative rounded-2xl p-8 text-ink overflow-hidden",
        gradients[variant],
        className
      )}
    >
      <div className="relative z-10">{children}</div>
      <div className="absolute inset-0 bg-gradient-to-br from-transparent to-black/20" />
    </div>
  );
}

interface SpotlightCardProps {
  children: ReactNode;
  className?: string;
}

export function SpotlightCard({ children, className }: SpotlightCardProps) {
  return (
    <div
      className={cn(
        "relative bg-surface-1 border border-hairline rounded-xl p-lg overflow-hidden group",
        className
      )}
    >
      <div className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-500">
        <div className="absolute inset-0 bg-gradient-to-br from-accent-blue/10 to-transparent" />
      </div>
      <div className="relative z-10">{children}</div>
    </div>
  );
}
