"use client";

import { useEffect, useState } from "react";
import { useAuthStore } from "@/stores/auth-store";
import { defaultSettings, useSettingsStore } from "@/stores/settings-store";
import { authService } from "@/services/auth-service";
import { apiService } from "@/services/api-service";
import type { UserSettings } from "@/types";

function isUnauthorized(error: unknown) {
  return error instanceof Error && (error as Error & { status?: number }).status === 401;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [isHydrated, setIsHydrated] = useState(false);
  const { login, logout, setLoading } = useAuthStore();
  const { setSettings } = useSettingsStore();

  useEffect(() => {
    let mounted = true;

    Promise.resolve(useAuthStore.persist.rehydrate()).finally(() => {
      if (mounted) setIsHydrated(true);
    });

    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    if (!isHydrated) return;

    let mounted = true;
    const resetAuthState = () => {
      apiService.clearTokens();
      logout();
      setSettings(defaultSettings);
    };

    setLoading(true);

    const resolveUser = async (): Promise<{ user: ReturnType<typeof useAuthStore.getState>["user"]; shouldReset: boolean }> => {
      const persistedUser = useAuthStore.getState().user;
      try {
        const user = await authService.getCurrentUser();
        if (user) return { user, shouldReset: false };
      } catch (error) {
        if (!isUnauthorized(error)) return { user: persistedUser, shouldReset: false };
      }

      try {
        const user = await authService.refreshSession();
        return { user, shouldReset: !user };
      } catch (error) {
        if (!isUnauthorized(error)) return { user: persistedUser, shouldReset: false };
        return { user: null, shouldReset: true };
      }
    };

    resolveUser()
      .then(({ user, shouldReset }) => {
        if (!mounted) return;
        if (user) {
          login(user);
          apiService
            .request<UserSettings>("/api/settings", { cacheTtlMs: 30_000, timeoutMs: 3_500 })
            .then((settings) => {
              if (mounted) setSettings(settings);
            })
            .catch(() => {
              // Keep locally persisted settings if the settings endpoint is unavailable.
            });
        } else if (shouldReset) {
          resetAuthState();
        }
      })
      .catch(() => {
        if (mounted && !apiService.getRefreshToken()) resetAuthState();
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });

    return () => {
      mounted = false;
    };
  }, [isHydrated, login, logout, setLoading, setSettings]);

  if (!isHydrated) {
    return null; // or a loading spinner
  }

  return <>{children}</>;
}
