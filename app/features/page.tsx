import { LandingLayout } from "@/layouts/landing-layout";
import { FeaturesSection } from "@/features/landing/features-section";
import { AgentArchitecture } from "@/features/landing/agent-architecture";
import { Footer } from "@/features/landing/footer";

export default function FeaturesPage() {
  return (
    <LandingLayout>
      <div className="pt-24 pb-12">
        <div className="text-center max-w-3xl mx-auto px-4">
          <h1 className="text-display-lg text-ink mb-6 tracking-tight">Platform Features</h1>
          <p className="text-subhead text-ink-muted">
            Explore the tools and agents designed to help you ace your next interview.
          </p>
        </div>
      </div>
      <FeaturesSection />
      <AgentArchitecture />
      <Footer />
    </LandingLayout>
  );
}
