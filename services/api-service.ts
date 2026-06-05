const LOCAL_BACKEND_FALLBACK_URL = "http://127.0.0.1:8000";
const PRODUCTION_BACKEND_FALLBACK_URL = "https://interviewos-backend-b71b2d354ad5.herokuapp.com";
const CONFIGURED_API_BASE_URL = process.env.NEXT_PUBLIC_API_URL?.trim().replace(/\/$/, "");
const API_BASE_URL =
  CONFIGURED_API_BASE_URL ||
  (process.env.NODE_ENV === "production"
    ? PRODUCTION_BACKEND_FALLBACK_URL
    : LOCAL_BACKEND_FALLBACK_URL);

const TOKEN_KEY = "interviewos-access-token";
const REFRESH_TOKEN_KEY = "interviewos-refresh-token";

type RequestOptions = Omit<RequestInit, "body"> & {
  body?: BodyInit | object | null;
  auth?: boolean;
  dedupe?: boolean;
  cacheTtlMs?: number;
  forceRefresh?: boolean;
  timeoutMs?: number;
};

type AuthRefreshResponse = {
  token?: string;
  access_token?: string;
  refresh_token?: string;
};

class APIService {
  baseURL = API_BASE_URL;
  private inFlightRequests = new Map<string, Promise<unknown>>();
  private responseCache = new Map<string, { expiresAt: number; value: unknown }>();
  private refreshInFlight: Promise<string | null> | null = null;

  private localFallbackURL() {
    if (this.baseURL === LOCAL_BACKEND_FALLBACK_URL) return null;
    if (["http://127.0.0.1:8001", "http://localhost:8001"].includes(this.baseURL)) {
      return LOCAL_BACKEND_FALLBACK_URL;
    }
    return null;
  }

  getToken() {
    if (typeof window === "undefined") return null;
    return window.localStorage.getItem(TOKEN_KEY);
  }

  getRefreshToken() {
    if (typeof window === "undefined") return null;
    return window.localStorage.getItem(REFRESH_TOKEN_KEY);
  }

  setTokens(accessToken: string, refreshToken?: string) {
    if (typeof window === "undefined") return;
    const previousToken = window.localStorage.getItem(TOKEN_KEY);
    window.localStorage.setItem(TOKEN_KEY, accessToken);
    if (refreshToken) {
      window.localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
    }
    if (previousToken !== accessToken) this.clearResponseCache();
  }

  clearTokens() {
    if (typeof window === "undefined") return;
    window.localStorage.removeItem(TOKEN_KEY);
    window.localStorage.removeItem(REFRESH_TOKEN_KEY);
    this.clearResponseCache();
  }

  clearResponseCache() {
    this.inFlightRequests.clear();
    this.responseCache.clear();
  }

  private refreshAccessToken(timeoutMs: number) {
    const refreshToken = this.getRefreshToken();
    if (!refreshToken) return Promise.resolve(null);
    if (this.refreshInFlight) return this.refreshInFlight;

    this.refreshInFlight = (async () => {
      const headers = new Headers({ "Content-Type": "application/json" });
      const init: RequestInit = {
        method: "POST",
        headers,
        body: JSON.stringify({ refresh_token: refreshToken }),
      };

      let response: Response;
      try {
        response = await this.fetchWithTimeout(`${this.baseURL}/api/auth/refresh`, init, timeoutMs);
      } catch {
        const fallbackURL = this.localFallbackURL();
        if (!fallbackURL) {
          this.clearTokens();
          return null;
        }
        try {
          response = await this.fetchWithTimeout(`${fallbackURL}/api/auth/refresh`, init, timeoutMs);
          this.baseURL = fallbackURL;
        } catch {
          this.clearTokens();
          return null;
        }
      }

      if (!response.ok) {
        this.clearTokens();
        return null;
      }

      const payload = (await response.json()) as AuthRefreshResponse;
      const accessToken = payload.access_token || payload.token;
      if (!accessToken) {
        this.clearTokens();
        return null;
      }
      this.setTokens(accessToken, payload.refresh_token);
      return accessToken;
    })().finally(() => {
      this.refreshInFlight = null;
    });

    return this.refreshInFlight;
  }

  private requestKey(endpoint: string, method: string, auth: boolean, token: string | null) {
    return `${method}:${this.baseURL}:${endpoint}:${auth ? token || "anonymous" : "public"}`;
  }

  private fetchWithTimeout(url: string, init: RequestInit, timeoutMs: number) {
    if (!timeoutMs || timeoutMs <= 0) {
      return fetch(url, init);
    }

    const controller = new AbortController();
    const externalSignal = init.signal;
    const timeoutId = globalThis.setTimeout(() => controller.abort(), timeoutMs);
    const abortFromExternalSignal = () => controller.abort(externalSignal?.reason);

    if (externalSignal?.aborted) {
      controller.abort(externalSignal.reason);
    } else {
      externalSignal?.addEventListener("abort", abortFromExternalSignal, { once: true });
    }

    return fetch(url, { ...init, signal: controller.signal }).finally(() => {
      globalThis.clearTimeout(timeoutId);
      externalSignal?.removeEventListener("abort", abortFromExternalSignal);
    });
  }

  private isAbortError(error: unknown) {
    return (
      typeof error === "object" &&
      error !== null &&
      "name" in error &&
      (error as { name?: unknown }).name === "AbortError"
    );
  }

  private timeoutMessage(endpoint: string, timeoutMs: number) {
    const seconds = Math.max(1, Math.round(timeoutMs / 1000));
    return `Backend request to ${endpoint} timed out after ${seconds}s. The server may be running, but this endpoint is taking too long.`;
  }

  private unreachableMessage(primaryURL: string, fallbackURL?: string | null) {
    const targets = fallbackURL ? `${primaryURL} or ${fallbackURL}` : primaryURL;
    if (process.env.NODE_ENV === "production") {
      return `Cannot reach backend at ${targets}. Check that the Heroku backend is awake and that Vercel was redeployed with NEXT_PUBLIC_API_URL set to the Heroku URL.`;
    }
    return `Cannot reach backend at ${targets}. Start the FastAPI server and try again.`;
  }

  async request<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
    const {
      body,
      auth = true,
      headers,
      dedupe,
      cacheTtlMs = 0,
      forceRefresh = false,
      timeoutMs = 0,
      ...rest
    } = options;
    const requestHeaders = new Headers(headers);
    const method = (rest.method || "GET").toUpperCase();
    const token = auth ? this.getToken() : null;
    const canReuse = method === "GET" && body === undefined;
    const key = canReuse ? this.requestKey(endpoint, method, auth, token) : "";

    let requestBody = body as BodyInit | undefined;
    if (body && !(body instanceof FormData) && typeof body !== "string") {
      requestHeaders.set("Content-Type", "application/json");
      requestBody = JSON.stringify(body);
    }

    if (auth && token) {
      requestHeaders.set("Authorization", `Bearer ${token}`);
    }

    if (canReuse && !forceRefresh) {
      const cached = this.responseCache.get(key);
      if (cached && cached.expiresAt > Date.now()) {
        return cached.value as T;
      }
      const active = this.inFlightRequests.get(key);
      if (active && dedupe !== false) {
        return active as Promise<T>;
      }
    }

    const execute = async () => {
      let response: Response;
      try {
        response = await this.fetchWithTimeout(`${this.baseURL}${endpoint}`, {
          ...rest,
          method,
          body: requestBody,
          headers: requestHeaders,
        }, timeoutMs);
      } catch (error) {
        if (this.isAbortError(error)) {
          throw new Error(this.timeoutMessage(endpoint, timeoutMs));
        }
        const fallbackURL = this.localFallbackURL();
        if (fallbackURL) {
          try {
            response = await this.fetchWithTimeout(`${fallbackURL}${endpoint}`, {
              ...rest,
              method,
              body: requestBody,
              headers: requestHeaders,
            }, timeoutMs);
            this.baseURL = fallbackURL;
          } catch (fallbackError) {
            if (this.isAbortError(fallbackError)) {
              throw new Error(this.timeoutMessage(endpoint, timeoutMs));
            }
            throw new Error(this.unreachableMessage(this.baseURL, fallbackURL));
          }
        } else {
          throw new Error(this.unreachableMessage(this.baseURL));
        }
      }

      if (response.status === 401 && auth && endpoint !== "/api/auth/refresh") {
        const refreshedToken = await this.refreshAccessToken(timeoutMs);
        if (refreshedToken) {
          requestHeaders.set("Authorization", `Bearer ${refreshedToken}`);
          response = await this.fetchWithTimeout(`${this.baseURL}${endpoint}`, {
            ...rest,
            method,
            body: requestBody,
            headers: requestHeaders,
          }, timeoutMs);
        }
      }

      if (!response.ok) {
        let message = response.statusText;
        try {
          const payload = await response.json();
          message = payload.detail || message;
        } catch {
          // Keep the HTTP status text when the backend returns no JSON body.
        }
        const error = new Error(message) as Error & { status?: number };
        error.status = response.status;
        throw error;
      }

      const value = response.status === 204 ? undefined : await response.json();
      if (method !== "GET") {
        this.clearResponseCache();
      } else if (canReuse && cacheTtlMs > 0) {
        this.responseCache.set(key, { expiresAt: Date.now() + cacheTtlMs, value });
      }
      return value as T;
    };

    if (!canReuse) {
      return execute();
    }

    const promise = execute().finally(() => {
      this.inFlightRequests.delete(key);
    });
    this.inFlightRequests.set(key, promise);
    return promise;
  }
}

export const apiService = new APIService();
