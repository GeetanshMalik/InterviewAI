"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Logo } from "@/components/logo";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { useAuthStore } from "@/stores/auth-store";
import { authService } from "@/services/auth-service";
import { ROUTES } from "@/constants/routes";
import { LoadingSpinner } from "@/components/loading-state";
import { FadeIn } from "@/components/animated-container";
import { AuthSidePanel } from "@/components/auth-side-panel";

export default function SignupPage() {
  const router = useRouter();
  const { login } = useAuthStore();
  const [isLoading, setIsLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [formData, setFormData] = useState({
    name: "",
    email: "",
    password: "",
    confirmPassword: "",
    acceptTerms: false,
  });

  const showSocialNotice = (provider: string) => {
    setNotice(`${provider} signup is coming soon. Use email and password for now.`);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (formData.password !== formData.confirmPassword) {
      alert("Passwords don't match");
      return;
    }

    if (!formData.acceptTerms) {
      alert("Please accept the terms and conditions");
      return;
    }

    setIsLoading(true);

    try {
      const response = await authService.signup({
        name: formData.name,
        email: formData.email,
        password: formData.password,
      });
      login(response.user);
      setIsLoading(false);
      router.push(ROUTES.DASHBOARD);
    } catch (error) {
      setIsLoading(false);
      alert(error instanceof Error ? error.message : "Signup failed");
    }
  };

  return (
    <div className="flex h-screen overflow-hidden bg-[#050505]">
      <AuthSidePanel />
      <div className="relative flex h-screen w-full flex-col items-center justify-start overflow-y-auto bg-canvas p-8 py-12 lg:w-1/2 lg:p-16 xl:justify-center xl:p-24">
        <div className="absolute top-8 right-8">
          <Link href={ROUTES.HOME} className="text-body-sm text-ink-muted hover:text-ink transition-colors">
            Back to Home
          </Link>
        </div>
        
        <FadeIn className="w-full max-w-sm">
          <div className="mb-6 flex flex-col items-center sm:items-start">
            <Logo className="mb-6 hidden sm:flex" size="md" />
            <h1 className="text-display-sm text-ink mb-2 tracking-tight text-center sm:text-left text-2xl font-semibold">Create your account</h1>
            <p className="text-body-sm text-ink-muted text-center sm:text-left">
              Start your interview preparation journey
            </p>
          </div>

          <div className="space-y-3 mb-5">
            <Button
              type="button"
              variant="outline"
              onClick={() => showSocialNotice("Google")}
              className="w-full h-12 bg-transparent border-hairline hover:bg-surface-1 text-ink rounded-lg font-medium flex items-center justify-center gap-2"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 12 12 2"/><path d="M12 12 21.5 7.5"/><path d="M12 12 21.5 16.5"/><path d="M12 12 12 22"/><path d="M12 12 2.5 16.5"/><path d="M12 12 2.5 7.5"/></svg>
              Sign up with Google
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => showSocialNotice("GitHub")}
              className="w-full h-12 bg-transparent border-hairline hover:bg-surface-1 text-ink rounded-lg font-medium flex items-center justify-center gap-2"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4"/><path d="M9 18c-4.51 2-5-2-7-2"/></svg>
              Sign up with GitHub
            </Button>
          </div>

          {notice && (
            <div className="mb-5 rounded-lg border border-hairline bg-surface-1 px-4 py-3 text-body-sm text-ink-muted">
              {notice}
            </div>
          )}

          <div className="flex items-center gap-4 mb-5">
            <div className="h-px bg-hairline flex-1" />
            <span className="text-micro text-ink-muted">Or use email</span>
            <div className="h-px bg-hairline flex-1" />
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label htmlFor="name" className="text-body-sm font-medium text-ink">
                Full Name
              </label>
              <Input
                id="name"
                type="text"
                placeholder="John Doe"
                value={formData.name}
                onChange={(e) =>
                  setFormData({ ...formData, name: e.target.value })
                }
                required
                className="bg-surface-1 border-hairline text-ink rounded-lg h-12 focus:ring-primary/50"
              />
            </div>

            <div className="space-y-1.5">
              <label htmlFor="email" className="text-body-sm font-medium text-ink">
                Email
              </label>
              <Input
                id="email"
                type="email"
                placeholder="you@example.com"
                value={formData.email}
                onChange={(e) =>
                  setFormData({ ...formData, email: e.target.value })
                }
                required
                className="bg-surface-1 border-hairline text-ink rounded-lg h-12 focus:ring-primary/50"
              />
            </div>

            <div className="space-y-1.5">
              <label htmlFor="password" className="text-body-sm font-medium text-ink">
                Password
              </label>
              <Input
                id="password"
                type="password"
                placeholder="••••••••"
                value={formData.password}
                onChange={(e) =>
                  setFormData({ ...formData, password: e.target.value })
                }
                required
                className="bg-surface-1 border-hairline text-ink rounded-lg h-12 focus:ring-primary/50"
              />
            </div>

            <div className="space-y-1.5">
              <label htmlFor="confirmPassword" className="text-body-sm font-medium text-ink">
                Confirm Password
              </label>
              <Input
                id="confirmPassword"
                type="password"
                placeholder="••••••••"
                value={formData.confirmPassword}
                onChange={(e) =>
                  setFormData({ ...formData, confirmPassword: e.target.value })
                }
                required
                className="bg-surface-1 border-hairline text-ink rounded-lg h-12 focus:ring-primary/50"
              />
            </div>

            <div className="flex items-start gap-2 pt-2">
              <Checkbox
                id="terms"
                checked={formData.acceptTerms}
                onCheckedChange={(checked) =>
                  setFormData({ ...formData, acceptTerms: checked as boolean })
                }
                className="border-hairline data-[state=checked]:bg-primary data-[state=checked]:text-on-primary mt-1"
              />
              <label htmlFor="terms" className="text-micro text-ink-muted cursor-pointer leading-tight mt-0.5">
                I agree to the{" "}
                <Link href="/terms" className="text-ink font-medium hover:underline">
                  Terms of Service
                </Link>{" "}
                and{" "}
                <Link href="/privacy" className="text-ink font-medium hover:underline">
                  Privacy Policy
                </Link>
              </label>
            </div>

            <Button
              type="submit"
              disabled={isLoading}
              className="w-full bg-ink text-inverse-ink hover:bg-ink/90 rounded-lg h-12 mt-4 font-medium"
            >
              {isLoading ? <LoadingSpinner size="sm" /> : "Create account"}
            </Button>
          </form>

          <div className="mt-6 text-center">
            <p className="text-body-sm text-ink-muted">
              Already have an account?{" "}
              <Link
                href={ROUTES.LOGIN}
                className="text-ink hover:text-primary transition-colors font-medium"
              >
                Sign in
              </Link>
            </p>
          </div>
        </FadeIn>
      </div>
    </div>
  );
}
