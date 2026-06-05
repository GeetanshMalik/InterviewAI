import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { Roadmap, RoadmapState, Milestone, Task } from "@/types";

interface RoadmapStore extends RoadmapState {
  setRoadmaps: (roadmaps: Roadmap[]) => void;
  addRoadmap: (roadmap: Roadmap) => void;
  setActiveRoadmap: (roadmapId: string | null) => void;
  updateRoadmap: (roadmapId: string, updates: Partial<Roadmap>) => void;
  deleteRoadmap: (roadmapId: string) => void;
  toggleMilestone: (roadmapId: string, milestoneId: string) => void;
  toggleTask: (roadmapId: string, milestoneId: string, taskId: string) => void;
  setLoading: (isLoading: boolean) => void;
}

export const useRoadmapStore = create<RoadmapStore>()(
  persist(
    (set, get) => ({
      roadmaps: [],
      activeRoadmap: null,
      isLoading: false,

      setRoadmaps: (roadmaps) =>
        set({
          roadmaps,
          activeRoadmap: roadmaps.find((roadmap) => roadmap.isActive) || null,
        }),

      addRoadmap: (roadmap) =>
        set((state) => ({
          roadmaps: [
            roadmap,
            ...state.roadmaps
              .filter((item) => item.id !== roadmap.id)
              .map((item) => ({ ...item, isActive: roadmap.isActive ? false : item.isActive })),
          ],
          activeRoadmap: roadmap.isActive ? roadmap : state.activeRoadmap,
        })),

      setActiveRoadmap: (roadmapId) => {
        if (!roadmapId) {
          set({ activeRoadmap: null });
          return;
        }
        const roadmap = get().roadmaps.find((r) => r.id === roadmapId);
        if (roadmap) {
          set((state) => ({
            activeRoadmap: roadmap,
            roadmaps: state.roadmaps.map((r) => ({
              ...r,
              isActive: r.id === roadmapId,
            })),
          }));
        }
      },

      updateRoadmap: (roadmapId, updates) =>
        set((state) => ({
          roadmaps: state.roadmaps.map((r) =>
            r.id === roadmapId ? { ...r, ...updates, updatedAt: new Date() } : r
          ),
          activeRoadmap:
            state.activeRoadmap?.id === roadmapId
              ? { ...state.activeRoadmap, ...updates, updatedAt: new Date() }
              : state.activeRoadmap,
        })),

      deleteRoadmap: (roadmapId) =>
        set((state) => ({
          roadmaps: state.roadmaps.filter((r) => r.id !== roadmapId),
          activeRoadmap:
            state.activeRoadmap?.id === roadmapId ? null : state.activeRoadmap,
        })),

      toggleMilestone: (roadmapId, milestoneId) =>
        set((state) => {
          const roadmap = state.roadmaps.find((r) => r.id === roadmapId);
          if (!roadmap) return state;

          const updatedMilestones = roadmap.milestones.map((m) =>
            m.id === milestoneId ? { ...m, completed: !m.completed } : m
          );

          const completedMilestones = updatedMilestones.filter((m) => m.completed).length;
          const progress = (completedMilestones / updatedMilestones.length) * 100;

          return {
            roadmaps: state.roadmaps.map((r) =>
              r.id === roadmapId
                ? { ...r, milestones: updatedMilestones, progress }
                : r
            ),
            activeRoadmap:
              state.activeRoadmap?.id === roadmapId
                ? { ...state.activeRoadmap, milestones: updatedMilestones, progress }
                : state.activeRoadmap,
          };
        }),

      toggleTask: (roadmapId, milestoneId, taskId) =>
        set((state) => {
          const roadmap = state.roadmaps.find((r) => r.id === roadmapId);
          if (!roadmap) return state;

          const updatedMilestones = roadmap.milestones.map((m) => {
            if (m.id === milestoneId) {
              const updatedTasks = m.tasks.map((t) =>
                t.id === taskId ? { ...t, completed: !t.completed } : t
              );
              const allTasksCompleted = updatedTasks.every((t) => t.completed);
              return { ...m, tasks: updatedTasks, completed: allTasksCompleted };
            }
            return m;
          });

          const completedMilestones = updatedMilestones.filter((m) => m.completed).length;
          const progress = (completedMilestones / updatedMilestones.length) * 100;

          return {
            roadmaps: state.roadmaps.map((r) =>
              r.id === roadmapId
                ? { ...r, milestones: updatedMilestones, progress }
                : r
            ),
            activeRoadmap:
              state.activeRoadmap?.id === roadmapId
                ? { ...state.activeRoadmap, milestones: updatedMilestones, progress }
                : state.activeRoadmap,
          };
        }),

      setLoading: (isLoading) => set({ isLoading }),
    }),
    {
      name: "roadmap-storage",
    }
  )
);
