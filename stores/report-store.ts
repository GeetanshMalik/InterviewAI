import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { Report, ReportState } from "@/types";

interface ReportStore extends ReportState {
  setReports: (reports: Report[]) => void;
  addReport: (report: Report) => void;
  setCurrentReport: (reportId: string | null) => void;
  deleteReport: (reportId: string) => void;
  setLoading: (isLoading: boolean) => void;
}

export const useReportStore = create<ReportStore>()(
  persist(
    (set, get) => ({
      reports: [],
      currentReport: null,
      isLoading: false,

      setReports: (reports) =>
        set((state) => ({
          reports,
          currentReport: state.currentReport
            ? reports.find((report) => report.id === state.currentReport?.id) || null
            : null,
        })),

      addReport: (report) =>
        set((state) => ({
          reports: [report, ...state.reports.filter((item) => item.id !== report.id)],
        })),

      setCurrentReport: (reportId) => {
        if (!reportId) {
          set({ currentReport: null });
          return;
        }
        const report = get().reports.find((r) => r.id === reportId);
        set({ currentReport: report || null });
      },

      deleteReport: (reportId) =>
        set((state) => ({
          reports: state.reports.filter((r) => r.id !== reportId),
          currentReport:
            state.currentReport?.id === reportId ? null : state.currentReport,
        })),

      setLoading: (isLoading) => set({ isLoading }),
    }),
    {
      name: "report-storage",
    }
  )
);
