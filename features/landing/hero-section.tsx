"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";
import { ROUTES } from "@/constants/routes";
import { FadeIn, StaggerContainer, StaggerItem } from "@/components/animated-container";
import { ArrowRight, Sparkles } from "lucide-react";
import { useAuthStore } from "@/stores/auth-store";

export function HeroSection() {
  const { isAuthenticated } = useAuthStore();
  
  return (
    <section className="relative min-h-[90vh] flex items-center justify-center overflow-hidden">
      {/* Animated Background */}
      <div className="absolute inset-0 -z-10">
        <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-gradient-violet/20 rounded-full blur-3xl animate-pulse" />
        <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-gradient-magenta/20 rounded-full blur-3xl animate-pulse delay-1000" />
      </div>

      <div className="container mx-auto px-4">
        <StaggerContainer className="max-w-4xl mx-auto text-center">
          <StaggerItem>
            <div className="inline-flex items-center gap-2 bg-surface-1 border border-hairline rounded-pill px-4 py-2 mb-8">
              <Sparkles className="w-4 h-4 text-accent-blue" />
              <span className="text-body-sm text-ink-muted">
                AI-Powered Interview Intelligence
              </span>
            </div>
          </StaggerItem>

          <StaggerItem>
            <h1 className="text-display-xxl md:text-display-xl text-ink mb-6">
              Master Interviews with Multi-Agent AI
            </h1>
          </StaggerItem>

          <StaggerItem>
            <p className="text-subhead text-ink-muted max-w-2xl mx-auto mb-12">
              Experience the future of interview preparation with intelligent
              multi-agent workflows, real-time analytics, and personalized
              learning roadmaps.
            </p>
          </StaggerItem>

          <StaggerItem>
            <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
              <Button
                asChild
                size="lg"
                className="bg-primary text-on-primary hover:bg-primary/90 rounded-pill px-8"
              >
                <Link href={isAuthenticated ? ROUTES.INTERVIEW : ROUTES.SIGNUP}>
                  Start Interview
                  <ArrowRight className="ml-2 w-5 h-5" />
                </Link>
              </Button>
              <Button
                asChild
                size="lg"
                variant="outline"
                className="border-hairline text-ink hover:bg-surface-1 rounded-pill px-8"
              >
                <Link href="/features">View Features</Link>
              </Button>
            </div>
          </StaggerItem>

          <StaggerItem>
            <div className="mt-16 grid grid-cols-3 gap-8 max-w-2xl mx-auto">
              <div>
                <div className="text-display-md text-ink mb-1">12+</div>
                <div className="text-body-sm text-ink-muted">AI Agents</div>
              </div>
              <div>
                <div className="text-display-md text-ink mb-1">100%</div>
                <div className="text-body-sm text-ink-muted">Personalized</div>
              </div>
              <div>
                <div className="text-display-md text-ink mb-1">24/7</div>
                <div className="text-body-sm text-ink-muted">Available</div>
              </div>
            </div>
          </StaggerItem>
        </StaggerContainer>
      </div>
    </section>
  );
}
