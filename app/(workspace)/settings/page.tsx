"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { codeLanguages } from "@/constants/code-languages";
import { jobRoleGroups } from "@/constants/job-roles";
import { interviewVoiceProfiles } from "@/constants/voice-profiles";
import { clearAllInterviewAutosaves } from "@/lib/interview-autosave";
import { cn } from "@/lib/utils";
import { apiService } from "@/services/api-service";
import { useAuthStore } from "@/stores/auth-store";
import { useInterviewStore } from "@/stores/interview-store";
import { defaultSettings, useSettingsStore } from "@/stores/settings-store";
import type { CompanyStyle, DifficultyLevel, User as AppUser, UserSettings } from "@/types";
import { Bot, BriefcaseBusiness, FileText, Save, Shield } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

const tabs = [
  { value: "interview", label: "Interview", icon: BriefcaseBusiness },
  { value: "ai", label: "AI", icon: Bot },
  { value: "security", label: "Privacy", icon: Shield },
] as const;

type SettingsTab = (typeof tabs)[number]["value"];
type SettingsSection = keyof UserSettings;

const roleOptions = Array.from(
  new Set(jobRoleGroups.flatMap((group) => group.roles))
).sort((a, b) => a.localeCompare(b));

const cloneSettings = (settings: UserSettings) =>
  JSON.parse(JSON.stringify(settings)) as UserSettings;

const serializeSettings = (settings: UserSettings) => JSON.stringify(settings);

function hydrateSettings(
  settings: Partial<UserSettings>,
  user: AppUser | null
): UserSettings {
  return {
    ...defaultSettings,
    ...settings,
    profile: {
      ...defaultSettings.profile,
      ...settings.profile,
      name: settings.profile?.name || user?.name || "",
      email: user?.email || settings.profile?.email || "",
      avatar: settings.profile?.avatar || user?.avatar,
    },
    ai: { ...defaultSettings.ai, ...settings.ai },
    memory: { ...defaultSettings.memory, ...settings.memory },
    integrations: { ...defaultSettings.integrations, ...settings.integrations },
    appearance: { ...defaultSettings.appearance, ...settings.appearance },
    security: { ...defaultSettings.security, ...settings.security },
    notifications: { ...defaultSettings.notifications, ...settings.notifications },
    interview: { ...defaultSettings.interview, ...settings.interview },
  };
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return <label className="text-body-sm font-medium text-ink">{children}</label>;
}

function ToggleRow({
  title,
  description,
  checked,
  onCheckedChange,
  disabled = false,
}: {
  title: string;
  description: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border border-hairline bg-surface-2/50 p-4">
      <div>
        <div className="text-body-sm font-medium text-ink">{title}</div>
        <div className="text-caption text-ink-muted">{description}</div>
      </div>
      <Switch checked={checked} onCheckedChange={onCheckedChange} disabled={disabled} />
    </div>
  );
}

export default function SettingsPage() {
  const { settings, setSettings } = useSettingsStore();
  const clearExecutionLogs = useInterviewStore((state) => state.clearExecutionLogs);
  const { user, updateUser } = useAuthStore();
  const userName = user?.name || "";
  const userEmail = user?.email || "";
  const userAvatar = user?.avatar;
  const [activeTab, setActiveTab] = useState<SettingsTab>("interview");
  const [draft, setDraft] = useState<UserSettings>(() =>
    hydrateSettings(settings, user)
  );
  const [saved, setSaved] = useState<UserSettings>(() =>
    hydrateSettings(settings, user)
  );
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [status, setStatus] = useState("");

  const isDirty = useMemo(
    () => serializeSettings(draft) !== serializeSettings(saved),
    [draft, saved]
  );

  useEffect(() => {
    let mounted = true;
    setIsLoading(true);

    apiService
      .request<UserSettings>("/api/settings", { cacheTtlMs: 30_000 })
      .then((remote) => {
        if (!mounted) return;
        const hydrated = hydrateSettings(remote, user);
        setSettings(hydrated);
        setDraft(cloneSettings(hydrated));
        setSaved(cloneSettings(hydrated));
      })
      .catch((error) => {
        if (!mounted) return;
        const local = hydrateSettings(useSettingsStore.getState().settings, user);
        setDraft(cloneSettings(local));
        setSaved(cloneSettings(local));
        setStatus(error instanceof Error ? error.message : "Settings loaded locally.");
      })
      .finally(() => {
        if (mounted) setIsLoading(false);
      });

    return () => {
      mounted = false;
    };
  }, [setSettings, user, userAvatar, userEmail, userName]);

  const updateDraft = <T extends SettingsSection>(
    section: T,
    value: Partial<UserSettings[T]>
  ) => {
    setStatus("");
    setDraft((current) => ({
      ...current,
      [section]: {
        ...current[section],
        ...value,
      },
    }));
  };

  const saveSettings = async () => {
    setIsSaving(true);
    setStatus("");
    try {
      const updated = await apiService.request<UserSettings>("/api/settings", {
        method: "PUT",
        body: draft,
      });
      const hydrated = hydrateSettings(updated, user);
      setSettings(hydrated);
      if (!hydrated.interview.showExecutionLogs) {
        clearExecutionLogs();
      }
      if (!hydrated.interview.autoSaveAnswers) {
        clearAllInterviewAutosaves();
      }
      setDraft(cloneSettings(hydrated));
      setSaved(cloneSettings(hydrated));
      updateUser({
        name: hydrated.profile.name,
        avatar: hydrated.profile.avatar,
      });
      setStatus("Settings saved.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Settings save failed.");
    } finally {
      setIsSaving(false);
    }
  };

  const handleChangePassword = async () => {
    if (!oldPassword || !newPassword) return;
    setIsSaving(true);
    setStatus("");
    try {
      await apiService.request("/api/settings/change-password", {
        method: "POST",
        body: { old_password: oldPassword, new_password: newPassword },
      });
      setOldPassword("");
      setNewPassword("");
      setStatus("Password updated.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Password update failed.");
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-display-lg text-ink mb-2">Settings</h1>
          <p className="text-body text-ink-muted">
            Manage interview defaults, AI behavior, and account security
          </p>
        </div>
        {isDirty && (
          <Button
            onClick={saveSettings}
            disabled={isSaving || isLoading}
            className="w-full rounded-lg bg-primary text-on-primary lg:w-auto"
          >
            <Save className="mr-2 h-4 w-4" />
            {isSaving ? "Saving..." : "Save Changes"}
          </Button>
        )}
      </div>

      {status && (
        <div className="rounded-lg border border-hairline bg-surface-1 px-4 py-3 text-body-sm text-ink-muted">
          {status}
        </div>
      )}

      <div className="flex gap-1 overflow-x-auto rounded-lg border border-hairline bg-surface-1 p-1">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.value;

          return (
            <button
              key={tab.value}
              onClick={() => setActiveTab(tab.value)}
              className={cn(
                "flex items-center gap-2 whitespace-nowrap rounded-md px-4 py-2.5 text-body-sm font-medium transition-colors",
                isActive
                  ? "bg-surface-2 text-ink"
                  : "text-ink-muted hover:bg-surface-2/50 hover:text-ink"
              )}
            >
              <Icon className="h-4 w-4" />
              {tab.label}
            </button>
          );
        })}
      </div>


      {activeTab === "interview" && (
        <Card className="bg-surface-1 border-hairline">
          <CardHeader>
            <CardTitle className="text-headline text-ink">Interview Defaults</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-5 lg:grid-cols-2">
            <div className="space-y-2">
              <FieldLabel>Default Role</FieldLabel>
              <Input
                list="settings-role-options"
                value={draft.interview.defaultRole}
                onChange={(event) =>
                  updateDraft("interview", { defaultRole: event.target.value })
                }
                placeholder="Search or type any role"
                className="h-12 rounded-lg bg-surface-2 border-hairline text-ink"
              />
              <datalist id="settings-role-options">
                {roleOptions.map((role) => (
                  <option key={role} value={role} />
                ))}
              </datalist>
            </div>
            <div className="space-y-2">
              <FieldLabel>Company Style</FieldLabel>
              <Select
                value={draft.interview.defaultCompanyStyle}
                onValueChange={(value) =>
                  updateDraft("interview", { defaultCompanyStyle: value as CompanyStyle })
                }
              >
                <SelectTrigger className="h-12 rounded-lg bg-surface-2 border-hairline">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="faang">FAANG</SelectItem>
                  <SelectItem value="startup">Startup</SelectItem>
                  <SelectItem value="enterprise">Enterprise</SelectItem>
                  <SelectItem value="product">Product Company</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <FieldLabel>Default Difficulty</FieldLabel>
              <Select
                value={draft.ai.defaultDifficulty}
                onValueChange={(value) =>
                  updateDraft("ai", { defaultDifficulty: value as DifficultyLevel })
                }
              >
                <SelectTrigger className="h-12 rounded-lg bg-surface-2 border-hairline">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="easy">Easy</SelectItem>
                  <SelectItem value="medium">Medium</SelectItem>
                  <SelectItem value="hard">Hard</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <FieldLabel>Coding Language</FieldLabel>
              <Select
                value={draft.interview.defaultLanguage}
                onValueChange={(value) =>
                  updateDraft("interview", { defaultLanguage: value })
                }
              >
                <SelectTrigger className="h-12 rounded-lg bg-surface-2 border-hairline">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {codeLanguages.map((language) => (
                    <SelectItem key={language.value} value={language.value}>
                      {language.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <FieldLabel>Practice Questions</FieldLabel>
              <Input
                type="number"
                min={5}
                max={30}
                value={draft.interview.practiceQuestionCount}
                onChange={(event) =>
                  updateDraft("interview", {
                    practiceQuestionCount: Math.min(30, Math.max(5, Number(event.target.value) || 20)),
                  })
                }
                className="h-12 rounded-lg bg-surface-2 border-hairline text-ink"
              />
            </div>
            <div className="space-y-3 lg:col-span-2">
              <ToggleRow
                title="Show execution logs"
                description="Keep interview orchestration logs visible during live rounds."
                checked={draft.interview.showExecutionLogs}
                disabled={isSaving || isLoading}
                onCheckedChange={(checked) =>
                  updateDraft("interview", { showExecutionLogs: checked })
                }
              />
              <ToggleRow
                title="Auto-save answers"
                description="Preserve written answers and code while moving between rounds."
                checked={draft.interview.autoSaveAnswers}
                disabled={isSaving || isLoading}
                onCheckedChange={(checked) =>
                  updateDraft("interview", { autoSaveAnswers: checked })
                }
              />
            </div>
          </CardContent>
        </Card>
      )}

      {activeTab === "ai" && (
        <Card className="bg-surface-1 border-hairline">
          <CardHeader>
            <CardTitle className="text-headline text-ink">AI Preferences</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-5 lg:grid-cols-2">
            <div className="space-y-2">
              <FieldLabel>Assistant Tone</FieldLabel>
              <Select
                value={draft.ai.personality}
                onValueChange={(value) =>
                  updateDraft("ai", { personality: value as UserSettings["ai"]["personality"] })
                }
              >
                <SelectTrigger className="h-12 rounded-lg bg-surface-2 border-hairline">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="professional">Professional</SelectItem>
                  <SelectItem value="friendly">Friendly</SelectItem>
                  <SelectItem value="direct">Direct</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <FieldLabel>Answer Style</FieldLabel>
              <Select
                value={draft.ai.responseStyle || "balanced"}
                onValueChange={(value) =>
                  updateDraft("ai", { responseStyle: value as UserSettings["ai"]["responseStyle"] })
                }
              >
                <SelectTrigger className="h-12 rounded-lg bg-surface-2 border-hairline">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="concise">Concise</SelectItem>
                  <SelectItem value="balanced">Balanced</SelectItem>
                  <SelectItem value="detailed">Detailed</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <FieldLabel>Response Language</FieldLabel>
              <Input
                value={draft.ai.language}
                onChange={(event) =>
                  updateDraft("ai", { language: event.target.value })
                }
                className="h-12 rounded-lg bg-surface-2 border-hairline text-ink"
              />
            </div>
            <div className="space-y-2">
              <FieldLabel>Interview Voice</FieldLabel>
              <Select
                value={draft.ai.interviewVoiceProfile || "en-IN-female-1"}
                onValueChange={(value) =>
                  updateDraft("ai", { interviewVoiceProfile: value })
                }
              >
                <SelectTrigger className="h-12 rounded-lg bg-surface-2 border-hairline">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {interviewVoiceProfiles.map((voice) => (
                    <SelectItem key={voice.value} value={voice.value}>
                      {voice.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-caption text-ink-muted">
                Uses the closest installed female browser voice for the selected accent.
              </p>
            </div>
            <div className="space-y-3 lg:col-span-2">
              <ToggleRow
                title="Voice responses"
                description="Allow voice playback when voice features are available."
                checked={draft.ai.voiceEnabled}
                disabled={isSaving || isLoading}
                onCheckedChange={(checked) =>
                  updateDraft("ai", { voiceEnabled: checked })
                }
              />
              <ToggleRow
                title="AI memory"
                description="Let the assistant use saved interview and resume context."
                checked={Boolean(draft.ai.memoryEnabled)}
                disabled={isSaving || isLoading}
                onCheckedChange={(checked) =>
                  updateDraft("ai", { memoryEnabled: checked })
                }
              />
            </div>
          </CardContent>
        </Card>
      )}



      {activeTab === "security" && (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card className="bg-surface-1 border-hairline">
            <CardHeader>
              <CardTitle className="text-headline text-ink">Privacy</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <Button
                asChild
                variant="outline"
                className="h-12 w-full justify-start rounded-lg border-hairline bg-surface-2 text-ink"
              >
                <Link href="/privacy">
                  <FileText className="mr-2 h-4 w-4" />
                  Privacy Policy
                </Link>
              </Button>
              <Button
                asChild
                variant="outline"
                className="h-12 w-full justify-start rounded-lg border-hairline bg-surface-2 text-ink"
              >
                <Link href="/terms">
                  <Shield className="mr-2 h-4 w-4" />
                  Terms of Use
                </Link>
              </Button>
            </CardContent>
          </Card>

          <Card className="bg-surface-1 border-hairline">
            <CardHeader>
              <CardTitle className="text-headline text-ink">Password</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <FieldLabel>Current Password</FieldLabel>
                <Input
                  type="password"
                  value={oldPassword}
                  onChange={(event) => setOldPassword(event.target.value)}
                  className="h-12 rounded-lg bg-surface-2 border-hairline text-ink"
                />
              </div>
              <div className="space-y-2">
                <FieldLabel>New Password</FieldLabel>
                <Input
                  type="password"
                  value={newPassword}
                  onChange={(event) => setNewPassword(event.target.value)}
                  className="h-12 rounded-lg bg-surface-2 border-hairline text-ink"
                />
              </div>
              {(oldPassword || newPassword) && (
                <Button
                  onClick={handleChangePassword}
                  disabled={!oldPassword || !newPassword || isSaving}
                  className="rounded-lg bg-primary text-on-primary"
                >
                  {isSaving ? "Updating..." : "Update Password"}
                </Button>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
