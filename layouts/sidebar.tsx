"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSidebarStore } from "@/stores/sidebar-store";
import { Logo } from "@/components/logo";
import { SIDEBAR_ITEMS } from "@/constants/navigation";
import { ROUTES } from "@/constants/routes";
import { cn } from "@/lib/utils";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useInterviewStore } from "@/stores/interview-store";

function routePath(href: string) {
  return href.split("?")[0].split("#")[0] || href;
}

export function Sidebar() {
  const pathname = usePathname();
  const { isCollapsed, toggleSidebar } = useSidebarStore();
  const {
    isNavigationLocked,
    addExecutionLog,
    resetInterview,
  } = useInterviewStore();

  return (
    <aside
      className={cn(
        "fixed left-0 top-0 h-screen bg-surface-1 border-r border-hairline transition-all duration-300 z-40",
        isCollapsed ? "w-16" : "w-64"
      )}
    >
      <div className="flex flex-col h-full">
        {/* Logo and Toggle Button */}
        <div className={cn(
          "flex items-center gap-3 p-4 border-b border-hairline-soft",
          isCollapsed ? "justify-center" : "justify-between"
        )}>
          {!isCollapsed && <Logo size="sm" />}
          <Button
            variant="ghost"
            size="icon"
            onClick={toggleSidebar}
            className="text-ink-muted hover:text-ink hover:bg-surface-2 rounded-md"
          >
            {isCollapsed ? (
              <ChevronRight className="w-5 h-5" />
            ) : (
              <ChevronLeft className="w-5 h-5" />
            )}
          </Button>
        </div>

        {/* Navigation Items */}
        <nav className="flex-1 overflow-y-auto py-4">
          <ul className="space-y-1 px-2">
            {SIDEBAR_ITEMS.map((item) => {
              const Icon = item.icon;
              const itemPath = routePath(item.href);
              const startsNewInterview = itemPath === ROUTES.INTERVIEW && item.label === "New Interview";
              const isActive = pathname === itemPath;
              const isBlocked = isNavigationLocked && (startsNewInterview || itemPath !== ROUTES.INTERVIEW);

              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-disabled={isBlocked}
                    onClick={(event) => {
                      if (isBlocked) {
                        event.preventDefault();
                        addExecutionLog({
                          type: "warning",
                          agent: "AI Proctor",
                          message: startsNewInterview
                            ? "Finish or stop the active interview before starting a new one."
                            : "Sidebar navigation is locked while the interview is active.",
                        });
                        return;
                      }
                      if (startsNewInterview) {
                        resetInterview();
                      }
                    }}
                    className={cn(
                      "flex items-center gap-3 px-3 py-2.5 rounded-md transition-all",
                      "text-body-sm font-medium",
                      isBlocked
                        ? "cursor-not-allowed text-ink-muted/35 hover:bg-transparent hover:text-ink-muted/35"
                        : isActive
                        ? "bg-surface-2 text-ink"
                        : "text-ink-muted hover:text-ink hover:bg-surface-2/50"
                    )}
                    title={isCollapsed ? item.label : undefined}
                  >
                    <Icon className="w-5 h-5 flex-shrink-0" />
                    {!isCollapsed && <span>{item.label}</span>}
                    {isActive && !isCollapsed && (
                      <div className="ml-auto w-1 h-4 bg-accent-blue rounded-full" />
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </div>
    </aside>
  );
}
