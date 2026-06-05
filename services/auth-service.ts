import type { User } from "@/types";
import { apiService } from "./api-service";

interface LoginCredentials {
  email: string;
  password: string;
}

interface SignupData {
  name: string;
  email: string;
  password: string;
}

interface AuthResponse {
  user: User;
  token: string;
  access_token?: string;
  refresh_token?: string;
}

class AuthService {
  async login(credentials: LoginCredentials): Promise<AuthResponse> {
    const response = await apiService.request<AuthResponse>("/api/auth/login", {
      method: "POST",
      body: credentials,
      auth: false,
    });
    apiService.setTokens(response.access_token || response.token, response.refresh_token);
    return response;
  }

  async signup(data: SignupData): Promise<AuthResponse> {
    const response = await apiService.request<AuthResponse>("/api/auth/signup", {
      method: "POST",
      body: data,
      auth: false,
    });
    apiService.setTokens(response.access_token || response.token, response.refresh_token);
    return response;
  }

  async logout(): Promise<void> {
    try {
      await apiService.request("/api/auth/logout", {
        method: "POST",
        body: { refresh_token: apiService.getRefreshToken() },
        timeoutMs: 3_500,
      });
    } finally {
      apiService.clearTokens();
    }
  }

  async getCurrentUser(): Promise<User | null> {
    if (!apiService.getToken()) return null;
    return apiService.request<User>("/api/auth/me", {
      cacheTtlMs: 30_000,
      timeoutMs: 3_500,
    });
  }

  async refreshSession(): Promise<User | null> {
    const refreshToken = apiService.getRefreshToken();
    if (!refreshToken) return null;

    const response = await apiService.request<AuthResponse>("/api/auth/refresh", {
      method: "POST",
      body: { refresh_token: refreshToken },
      auth: false,
      timeoutMs: 3_500,
    });
    apiService.setTokens(response.access_token || response.token, response.refresh_token);
    return response.user;
  }
}

export const authService = new AuthService();
