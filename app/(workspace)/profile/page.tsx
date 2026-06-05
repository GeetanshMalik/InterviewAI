"use client";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { apiService } from "@/services/api-service";
import { useAuthStore } from "@/stores/auth-store";
import { defaultSettings, useSettingsStore } from "@/stores/settings-store";
import { useReportStore } from "@/stores/report-store";
import type { UserSettings } from "@/types";
import {
  BriefcaseBusiness,
  Camera,
  Github,
  Globe,
  Linkedin,
  Loader2,
  Mail,
  MapPin,
  Save,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

function mergeSettings(settings: Partial<UserSettings>, userName = "", userEmail = ""): UserSettings {
  return {
    ...defaultSettings,
    ...settings,
    profile: {
      ...defaultSettings.profile,
      ...settings.profile,
      name: settings.profile?.name || userName,
      email: settings.profile?.email || userEmail,
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

const cloneSettings = (settings: UserSettings) =>
  JSON.parse(JSON.stringify(settings)) as UserSettings;

const serializeProfile = (settings: UserSettings) => JSON.stringify(settings.profile);

function FieldLabel({ children }: { children: React.ReactNode }) {
  return <label className="text-body-sm font-medium text-ink">{children}</label>;
}

export default function ProfilePage() {
  const { user, updateUser } = useAuthStore();
  const { settings, setSettings } = useSettingsStore();
  const { reports } = useReportStore();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [draft, setDraft] = useState<UserSettings>(() =>
    mergeSettings(settings, user?.name || "", user?.email || "")
  );
  const [saved, setSaved] = useState<UserSettings>(() =>
    mergeSettings(settings, user?.name || "", user?.email || "")
  );
  const [isAvatarSaving, setIsAvatarSaving] = useState(false);
  const [isSavingProfile, setIsSavingProfile] = useState(false);
  const [avatarStatus, setAvatarStatus] = useState("");
  const [profileStatus, setProfileStatus] = useState("");
  const profile = draft.profile;

  const isProfileDirty = useMemo(
    () => serializeProfile(draft) !== serializeProfile(saved),
    [draft, saved]
  );

  useEffect(() => {
    let mounted = true;

    apiService
      .request<UserSettings>("/api/settings", { cacheTtlMs: 30_000 })
      .then((remote) => {
        if (!mounted) return;
        const merged = mergeSettings(remote, user?.name || "", user?.email || "");
        setSettings(merged);
        setDraft(cloneSettings(merged));
        setSaved(cloneSettings(merged));
      })
      .catch(() => {
        if (!mounted) return;
        const local = mergeSettings(
          useSettingsStore.getState().settings,
          user?.name || "",
          user?.email || ""
        );
        setSettings(local);
        setDraft(cloneSettings(local));
        setSaved(cloneSettings(local));
      });

    return () => {
      mounted = false;
    };
  }, [setSettings, user?.email, user?.name]);

  const summary = useMemo(() => {
    const average =
      reports.length > 0
        ? Math.round(
            reports.reduce((sum, report) => sum + report.overallScore, 0) /
              reports.length
          )
        : 0;
    const latest = reports[0]?.overallScore ? Math.round(reports[0].overallScore) : 0;
    const weakAreas = Array.from(
      new Set(reports.flatMap((report) => report.weaknesses || []))
    ).slice(0, 4);

    return { average, latest, weakAreas };
  }, [reports]);

  const updateProfileDraft = (profileUpdates: Partial<UserSettings["profile"]>) => {
    setAvatarStatus("");
    setProfileStatus("");
    setDraft((current) => ({
      ...current,
      profile: {
        ...current.profile,
        ...profileUpdates,
      },
    }));
  };

  const name = profile.name || user?.name || "User";
  const avatarSrc = profile.avatar || user?.avatar || "";
  const initials = name
    .split(" ")
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  const saveAvatar = async (avatar: string | null) => {
    setIsAvatarSaving(true);
    setAvatarStatus("");
    try {
      const nextSettings = {
        ...draft,
        profile: {
          ...draft.profile,
          avatar,
        },
      };
      const updated = await apiService.request<UserSettings>("/api/settings", {
        method: "PUT",
        body: nextSettings,
      });
      const merged = mergeSettings(updated, user?.name || "", user?.email || "");
      setSettings(merged);
      setDraft(cloneSettings(merged));
      setSaved(cloneSettings(merged));
      updateUser({ avatar: merged.profile.avatar || undefined });
      setAvatarStatus(avatar ? "Profile photo updated." : "Profile photo removed.");
    } catch (error) {
      setAvatarStatus(error instanceof Error ? error.message : "Unable to update profile photo.");
    } finally {
      setIsAvatarSaving(false);
    }
  };

  const handleAvatarFile = (file?: File) => {
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      setAvatarStatus("Choose an image file for your profile photo.");
      return;
    }
    if (file.size > 1.5 * 1024 * 1024) {
      setAvatarStatus("Use an image smaller than 1.5 MB.");
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") {
        void saveAvatar(reader.result);
      }
    };
    reader.onerror = () => setAvatarStatus("Unable to read this image file.");
    reader.readAsDataURL(file);
  };

  const saveProfile = async () => {
    setIsSavingProfile(true);
    setProfileStatus("");
    try {
      const updated = await apiService.request<UserSettings>("/api/settings", {
        method: "PUT",
        body: draft,
      });
      const merged = mergeSettings(updated, user?.name || "", user?.email || "");
      setSettings(merged);
      setDraft(cloneSettings(merged));
      setSaved(cloneSettings(merged));
      updateUser({
        name: merged.profile.name,
        avatar: merged.profile.avatar || undefined,
      });
      setProfileStatus("Profile saved.");
    } catch (error) {
      setProfileStatus(error instanceof Error ? error.message : "Unable to save profile.");
    } finally {
      setIsSavingProfile(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-display-lg text-ink mb-2">Profile</h1>
          <p className="text-body text-ink-muted">
            Your saved identity, preferences, and preparation snapshot
          </p>
        </div>
        <Button
          onClick={saveProfile}
          disabled={!isProfileDirty || isSavingProfile}
          className="w-full rounded-lg bg-primary text-on-primary lg:w-auto"
        >
          {isSavingProfile ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Save className="mr-2 h-4 w-4" />
          )}
          {isSavingProfile ? "Saving..." : "Save Profile"}
        </Button>
      </div>

      {profileStatus && (
        <div className="rounded-lg border border-hairline bg-surface-1 px-4 py-3 text-body-sm text-ink-muted">
          {profileStatus}
        </div>
      )}

      <Card className="bg-surface-1 border-hairline">
        <CardContent className="flex flex-col gap-6 p-6 lg:flex-row lg:items-center">
          <div className="space-y-3">
            <div className="relative h-24 w-24">
              <Avatar className="h-24 w-24 rounded-lg">
                <AvatarImage src={avatarSrc} />
                <AvatarFallback className="rounded-lg bg-surface-2 text-display-sm text-ink">
                  {initials || "U"}
                </AvatarFallback>
              </Avatar>
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={isAvatarSaving}
                className="absolute bottom-2 right-2 flex h-9 w-9 items-center justify-center rounded-md border border-hairline bg-surface-1 text-ink shadow-lg transition-colors hover:border-accent-blue"
                aria-label="Update profile photo"
              >
                {isAvatarSaving ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Camera className="h-4 w-4" />
                )}
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(event) => {
                  handleAvatarFile(event.target.files?.[0]);
                  event.target.value = "";
                }}
              />
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => fileInputRef.current?.click()}
                disabled={isAvatarSaving}
                className="rounded-md border-hairline"
              >
                <Camera className="mr-2 h-4 w-4" />
                Change
              </Button>
              {avatarSrc && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => saveAvatar(null)}
                  disabled={isAvatarSaving}
                  className="rounded-md border-hairline text-gradient-coral"
                >
                  <Trash2 className="mr-2 h-4 w-4" />
                  Remove
                </Button>
              )}
            </div>
            {avatarStatus && <p className="max-w-48 text-caption text-ink-muted">{avatarStatus}</p>}
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-display-sm text-ink">{name}</h2>
            {profile.headline && (
              <p className="mt-1 text-body text-ink-muted">{profile.headline}</p>
            )}
            <div className="mt-4 grid gap-2 text-body-sm text-ink-muted md:grid-cols-2">
              <div className="flex items-center gap-2">
                <Mail className="h-4 w-4 text-accent-blue" />
                <span className="truncate">{profile.email || user?.email}</span>
              </div>
              {profile.location && (
                <div className="flex items-center gap-2">
                  <MapPin className="h-4 w-4 text-accent-blue" />
                  <span>{profile.location}</span>
                </div>
              )}
              {settings.interview.defaultRole && (
                <div className="flex items-center gap-2">
                  <BriefcaseBusiness className="h-4 w-4 text-accent-blue" />
                  <span>{settings.interview.defaultRole}</span>
                </div>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="bg-surface-1 border-hairline">
        <CardHeader>
          <CardTitle className="text-headline text-ink">Profile Details</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-5 lg:grid-cols-2">
          <div className="space-y-2">
            <FieldLabel>Full Name</FieldLabel>
            <Input
              value={profile.name}
              onChange={(event) => updateProfileDraft({ name: event.target.value })}
              className="h-12 rounded-lg border-hairline bg-surface-2 text-ink"
            />
          </div>
          <div className="space-y-2">
            <FieldLabel>Email</FieldLabel>
            <Input
              type="email"
              value={profile.email || user?.email || ""}
              disabled
              className="h-12 rounded-lg border-hairline bg-surface-2/50 text-ink-muted"
            />
          </div>
          <div className="space-y-2">
            <FieldLabel>Professional Headline</FieldLabel>
            <Input
              value={profile.headline || ""}
              onChange={(event) => updateProfileDraft({ headline: event.target.value })}
              placeholder="Frontend Engineer - DSA Focus"
              className="h-12 rounded-lg border-hairline bg-surface-2 text-ink"
            />
          </div>
          <div className="space-y-2">
            <FieldLabel>Location</FieldLabel>
            <Input
              value={profile.location || ""}
              onChange={(event) => updateProfileDraft({ location: event.target.value })}
              placeholder="Bhopal, India"
              className="h-12 rounded-lg border-hairline bg-surface-2 text-ink"
            />
          </div>
          <div className="space-y-2">
            <FieldLabel>Portfolio</FieldLabel>
            <Input
              value={profile.website || ""}
              onChange={(event) => updateProfileDraft({ website: event.target.value })}
              placeholder="https://your-site.com"
              className="h-12 rounded-lg border-hairline bg-surface-2 text-ink"
            />
          </div>
          <div className="space-y-2">
            <FieldLabel>LinkedIn</FieldLabel>
            <Input
              value={profile.linkedin || ""}
              onChange={(event) => updateProfileDraft({ linkedin: event.target.value })}
              placeholder="https://linkedin.com/in/username"
              className="h-12 rounded-lg border-hairline bg-surface-2 text-ink"
            />
          </div>
          <div className="space-y-2">
            <FieldLabel>GitHub</FieldLabel>
            <Input
              value={profile.github || ""}
              onChange={(event) => updateProfileDraft({ github: event.target.value })}
              placeholder="https://github.com/username"
              className="h-12 rounded-lg border-hairline bg-surface-2 text-ink"
            />
          </div>
          <div className="space-y-2 lg:col-span-2">
            <FieldLabel>Bio</FieldLabel>
            <Textarea
              value={profile.bio || ""}
              onChange={(event) => updateProfileDraft({ bio: event.target.value })}
              placeholder="Short career summary"
              className="min-h-28 rounded-lg border-hairline bg-surface-2 text-ink"
            />
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="bg-surface-1 border-hairline">
          <CardHeader>
            <CardTitle className="text-headline text-ink">Preparation</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <div className="text-caption text-ink-muted">Average Score</div>
              <div className="text-display-sm text-ink">{summary.average}%</div>
            </div>
            <div>
              <div className="text-caption text-ink-muted">Latest Score</div>
              <div className="text-display-sm text-ink">{summary.latest}%</div>
            </div>
            <div>
              <div className="text-caption text-ink-muted">Completed Reports</div>
              <div className="text-display-sm text-ink">{reports.length}</div>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-surface-1 border-hairline">
          <CardHeader>
            <CardTitle className="text-headline text-ink">Defaults</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-body-sm">
            <div className="flex justify-between gap-4">
              <span className="text-ink-muted">Company Style</span>
              <span className="text-ink">{settings.interview.defaultCompanyStyle}</span>
            </div>
            <div className="flex justify-between gap-4">
              <span className="text-ink-muted">Difficulty</span>
              <span className="text-ink">{settings.ai.defaultDifficulty}</span>
            </div>
            <div className="flex justify-between gap-4">
              <span className="text-ink-muted">Language</span>
              <span className="text-ink">{settings.interview.defaultLanguage}</span>
            </div>
            <div className="flex justify-between gap-4">
              <span className="text-ink-muted">Practice Size</span>
              <span className="text-ink">{settings.interview.practiceQuestionCount}</span>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-surface-1 border-hairline">
          <CardHeader>
            <CardTitle className="text-headline text-ink">Focus Areas</CardTitle>
          </CardHeader>
          <CardContent>
            {summary.weakAreas.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {summary.weakAreas.map((area) => (
                  <span
                    key={area}
                    className="rounded-md border border-hairline bg-surface-2 px-2.5 py-1 text-caption text-ink-muted"
                  >
                    {area}
                  </span>
                ))}
              </div>
            ) : (
              <p className="text-body-sm text-ink-muted">
                Focus areas will appear after your first interview report.
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      {(profile.bio || profile.website || profile.linkedin || profile.github) && (
        <Card className="bg-surface-1 border-hairline">
          <CardHeader>
            <CardTitle className="text-headline text-ink">About</CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            {profile.bio && <p className="text-body text-ink-muted">{profile.bio}</p>}
            <div className="flex flex-wrap gap-3">
              {profile.website && (
                <a className="inline-flex items-center gap-2 text-body-sm text-accent-blue" href={profile.website}>
                  <Globe className="h-4 w-4" />
                  Portfolio
                </a>
              )}
              {profile.linkedin && (
                <a className="inline-flex items-center gap-2 text-body-sm text-accent-blue" href={profile.linkedin}>
                  <Linkedin className="h-4 w-4" />
                  LinkedIn
                </a>
              )}
              {profile.github && (
                <a className="inline-flex items-center gap-2 text-body-sm text-accent-blue" href={profile.github}>
                  <Github className="h-4 w-4" />
                  GitHub
                </a>
              )}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
