import { cn } from "@/lib/utils";
import { LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: {
    label: string;
    onClick: () => void;
  };
  className?: string;
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center py-16 px-4 text-center",
        className
      )}
    >
      <div className="mb-4 rounded-full bg-surface-1 p-6">
        <Icon className="w-12 h-12 text-ink-muted" />
      </div>
      <h3 className="text-headline text-ink mb-2">{title}</h3>
      <p className="text-body text-ink-muted max-w-md mb-6">{description}</p>
      {action && (
        <Button
          onClick={action.onClick}
          className="bg-primary text-on-primary rounded-pill"
        >
          {action.label}
        </Button>
      )}
    </div>
  );
}
