const AUTOSAVE_PREFIX = "interviewos-autosave";

function autosaveKey(interviewId: string, scope: string) {
  return `${AUTOSAVE_PREFIX}:${interviewId}:${scope}`;
}

export function readAutosavedValue<T>(interviewId: string | null, scope: string, fallback: T): T {
  if (!interviewId || typeof window === "undefined") return fallback;

  try {
    const raw = window.localStorage.getItem(autosaveKey(interviewId, scope));
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

export function writeAutosavedValue<T>(interviewId: string | null, scope: string, value: T) {
  if (!interviewId || typeof window === "undefined") return;

  try {
    window.localStorage.setItem(autosaveKey(interviewId, scope), JSON.stringify(value));
  } catch {
    // Autosave is a convenience layer; interview submission still uses in-memory state.
  }
}

export function clearAutosavedValue(interviewId: string | null, scope: string) {
  if (!interviewId || typeof window === "undefined") return;
  window.localStorage.removeItem(autosaveKey(interviewId, scope));
}

export function clearAllInterviewAutosaves() {
  if (typeof window === "undefined") return;

  for (let index = window.localStorage.length - 1; index >= 0; index -= 1) {
    const key = window.localStorage.key(index);
    if (key?.startsWith(`${AUTOSAVE_PREFIX}:`)) {
      window.localStorage.removeItem(key);
    }
  }
}
