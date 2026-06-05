"use client";

import { GradientCard } from "@/components/gradient-card";
import { Zap, Shield, Sparkles } from "lucide-react";

export function AboutSection() {
  return (
    <section className="py-section bg-surface-1/30">
      <div className="container mx-auto px-4">
        <div className="max-w-4xl mx-auto">
          <div className="text-center mb-16">
            <h2 className="text-display-lg text-ink mb-4">
              Built for the Future of Interviews
            </h2>
            <p className="text-subhead text-ink-muted">
              InterviewAI combines cutting-edge artificial intelligence with
              proven interview preparation methodologies to create an unparalleled
              learning experience.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-12">
            <GradientCard variant="violet">
              <Zap className="w-8 h-8 mb-4" />
              <h3 className="text-headline text-ink mb-2">Lightning Fast</h3>
              <p className="text-body text-ink/90">
                Real-time feedback and instant analysis powered by advanced AI
                models.
              </p>
            </GradientCard>

            <GradientCard variant="magenta">
              <Shield className="w-8 h-8 mb-4" />
              <h3 className="text-headline text-ink mb-2">Secure & Private</h3>
              <p className="text-body text-ink/90">
                Your data is encrypted and never shared. Complete privacy
                guaranteed.
              </p>
            </GradientCard>

            <GradientCard variant="orange">
              <Sparkles className="w-8 h-8 mb-4" />
              <h3 className="text-headline text-ink mb-2">Always Improving</h3>
              <p className="text-body text-ink/90">
                Continuous updates with new features and AI model improvements.
              </p>
            </GradientCard>
          </div>

          <div className="bg-surface-1 border border-hairline rounded-xl p-8 text-center">
            <h3 className="text-display-md text-ink mb-4">Our Mission</h3>
            <p className="text-body-lg text-ink-muted max-w-2xl mx-auto">
              To democratize access to world-class interview preparation by
              leveraging AI technology. We believe everyone deserves the
              opportunity to showcase their true potential in interviews.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
