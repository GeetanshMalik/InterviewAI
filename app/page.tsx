import { LandingLayout } from "@/layouts/landing-layout";
import { HeroSection } from "@/features/landing/hero-section";
import { AgentArchitecture } from "@/features/landing/agent-architecture";
import { FeaturesSection } from "@/features/landing/features-section";
import { PricingSection } from "@/features/landing/pricing-section";
import { FaqSection } from "@/features/landing/faq-section";
import { Footer } from "@/features/landing/footer";

export default function Home() {
  return (
    <LandingLayout>
      <HeroSection />
      <AgentArchitecture />
      <FeaturesSection />
      <PricingSection />
      <FaqSection />
      <Footer />
    </LandingLayout>
  );
}
