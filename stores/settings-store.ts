import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { UserSettings, SettingsState } from "@/types";
import { defaultInterviewVoiceProfile } from "@/constants/voice-profiles";

interface SettingsStore extends SettingsState {
  updateSettings: (settings: Partial<UserSettings>) => void;
  setSettings: (settings: UserSettings) => void;
  updateProfile: (profile: Partial<UserSettings["profile"]>) => void;
  updateAI: (ai: Partial<UserSettings["ai"]>) => void;
  updateInterview: (interview: Partial<UserSettings["interview"]>) => void;
  updateMemory: (memory: Partial<UserSettings["memory"]>) => void;
  updateNotifications: (notifications: Partial<UserSettings["notifications"]>) => void;
  updateAppearance: (appearance: Partial<UserSettings["appearance"]>) => void;
  setLoading: (isLoading: boolean) => void;
}

export const defaultSettings: UserSettings = {
  profile: {
    name: "",
    email: "",
    headline: "",
    location: "",
    website: "",
    linkedin: "",
    github: "",
    bio: "",
  },
  ai: {
    defaultDifficulty: "medium",
    personality: "professional",
    voiceEnabled: true,
    language: "en",
    interviewVoiceProfile: defaultInterviewVoiceProfile,
    memoryEnabled: true,
    responseStyle: "balanced",
  },
  memory: {
    dataRetentionDays: 90,
    allowDataCollection: true,
    storeChatHistory: true,
    includeResumeContext: true,
  },
  integrations: {},
  appearance: {
    theme: "dark",
    accentColor: "#6670f0",
    fontSize: "medium",
    compactDashboard: false,
    reduceMotion: false,
  },
  security: {
    twoFactorEnabled: false,
    activeSessions: [],
  },
  notifications: {
    emailReports: true,
    weeklyDigest: true,
    practiceReminders: false,
    roadmapReminders: true,
  },
  interview: {
    defaultRole: "",
    defaultCompanyStyle: "product",
    defaultLanguage: "javascript",
    practiceQuestionCount: 20,
    showExecutionLogs: true,
    autoSaveAnswers: true,
  },
};

function mergeSettings(settings: Partial<UserSettings>): UserSettings {
  return {
    ...defaultSettings,
    ...settings,
    profile: { ...defaultSettings.profile, ...settings.profile },
    ai: { ...defaultSettings.ai, ...settings.ai },
    memory: { ...defaultSettings.memory, ...settings.memory },
    integrations: { ...defaultSettings.integrations, ...settings.integrations },
    appearance: { ...defaultSettings.appearance, ...settings.appearance },
    security: { ...defaultSettings.security, ...settings.security },
    notifications: { ...defaultSettings.notifications, ...settings.notifications },
    interview: { ...defaultSettings.interview, ...settings.interview },
  };
}

export const useSettingsStore = create<SettingsStore>()(
  persist(
    (set) => ({
      settings: defaultSettings,
      isLoading: false,

      updateSettings: (newSettings) =>
        set((state) => ({
          settings: mergeSettings({ ...state.settings, ...newSettings }),
        })),

      setSettings: (settings) =>
        set({
          settings: mergeSettings(settings),
        }),

      updateProfile: (profile) =>
        set((state) => ({
          settings: {
            ...state.settings,
            profile: { ...state.settings.profile, ...profile },
          },
        })),

      updateAI: (ai) =>
        set((state) => ({
          settings: {
            ...state.settings,
            ai: { ...state.settings.ai, ...ai },
          },
        })),

      updateInterview: (interview) =>
        set((state) => ({
          settings: {
            ...state.settings,
            interview: { ...state.settings.interview, ...interview },
          },
        })),

      updateMemory: (memory) =>
        set((state) => ({
          settings: {
            ...state.settings,
            memory: { ...state.settings.memory, ...memory },
          },
        })),

      updateNotifications: (notifications) =>
        set((state) => ({
          settings: {
            ...state.settings,
            notifications: { ...state.settings.notifications, ...notifications },
          },
        })),

      updateAppearance: (appearance) =>
        set((state) => ({
          settings: {
            ...state.settings,
            appearance: { ...state.settings.appearance, ...appearance },
          },
        })),

      setLoading: (isLoading) => set({ isLoading }),
    }),
    {
      name: "settings-storage",
      merge: (persisted, current) => {
        const persistedState = persisted as Partial<SettingsStore> | undefined;
        return {
          ...current,
          ...persistedState,
          settings: mergeSettings(persistedState?.settings || current.settings),
        };
      },
    }
  )
);
