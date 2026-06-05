import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { SidebarState } from "@/types";

interface SidebarStore extends SidebarState {
  toggleSidebar: () => void;
  setActiveRoute: (route: string) => void;
  collapseSidebar: () => void;
  expandSidebar: () => void;
}

export const useSidebarStore = create<SidebarStore>()(
  persist(
    (set) => ({
      isCollapsed: false,
      activeRoute: "/dashboard",

      toggleSidebar: () =>
        set((state) => ({
          isCollapsed: !state.isCollapsed,
        })),

      setActiveRoute: (route) => set({ activeRoute: route }),

      collapseSidebar: () => set({ isCollapsed: true }),

      expandSidebar: () => set({ isCollapsed: false }),
    }),
    {
      name: "sidebar-storage",
    }
  )
);
