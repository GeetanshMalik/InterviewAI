"use client";

import { ReactNode } from "react";
import { usePathname } from "next/navigation";
import { Sidebar } from "./sidebar";
import { useSidebarStore } from "@/stores/sidebar-store";
import { cn } from "@/lib/utils";

interface WorkspaceLayoutProps {
  children: ReactNode;
}

export function WorkspaceLayout({ children }: WorkspaceLayoutProps) {
  const { isCollapsed } = useSidebarStore();
  const pathname = usePathname();
  const isInterviewPage = pathname === "/interview";

  return (
    <div className={cn("bg-canvas", isInterviewPage ? "h-screen overflow-hidden" : "min-h-screen")}>
      <Sidebar />
      <main
        className={cn(
          "transition-all duration-300",
          isCollapsed ? "ml-16" : "ml-64",
          isInterviewPage && "h-screen overflow-hidden"
        )}
      >
        <div className={cn("container mx-auto px-4", isInterviewPage ? "box-border h-full overflow-hidden py-4" : "py-8")}>
          {children}
        </div>
      </main>
    </div>
  );
}
