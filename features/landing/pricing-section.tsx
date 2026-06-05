"use client";

import { Coffee, Copy, Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { FadeIn, StaggerContainer, StaggerItem } from "@/components/animated-container";
import Link from "next/link";
import { ROUTES } from "@/constants/routes";
import { useAuthStore } from "@/stores/auth-store";

const supportUpiId = "geetanshmalik337@okaxis";
const supportUpiUri = `upi://pay?pa=${supportUpiId}&pn=Geetansh%20Malik&cu=INR`;
const supportQrCodeUrl = `https://api.qrserver.com/v1/create-qr-code/?size=280x280&margin=16&data=${encodeURIComponent(
  supportUpiUri
)}`;

const plans = [
  {
    name: "Hobby",
    price: "$0",
    description: "Perfect for students getting started.",
    features: [
      "1 Mock Interview per month",
      "Basic feedback dashboard",
      "Standard agent persona",
      "Community support"
    ],
    missing: [
      "Audio-visual analysis",
      "Personalized roadmap",
      "Priority agent orchestration",
      "Live code execution"
    ],
    buttonText: "Start for free",
    buttonVariant: "outline"
  },
  {
    name: "Pro",
    price: "$29",
    period: "/mo",
    description: "For serious candidates aiming for FAANG.",
    popular: true,
    features: [
      "Unlimited Mock Interviews",
      "Cinematic multi-agent workflow",
      "Full audio-visual behavioral analysis",
      "Personalized career roadmap",
      "Live code execution environment",
      "Priority email support"
    ],
    missing: [],
    buttonText: "Upgrade to Pro",
    buttonVariant: "default"
  }
];

export function PricingSection() {
  const { isAuthenticated, user } = useAuthStore();
  const accountHref = isAuthenticated || user ? ROUTES.DASHBOARD : ROUTES.SIGNUP;

  return (
    <section className="py-32 relative">
      <div className="container mx-auto px-4">
        <FadeIn>
          <div className="text-center max-w-3xl mx-auto mb-20">
            <h2 className="text-display-lg text-ink mb-6 tracking-tight">Invest in your career</h2>
            <p className="text-subhead text-ink-muted">
              Transparent pricing for the ultimate interview preparation system.
            </p>
          </div>
        </FadeIn>

        <StaggerContainer className="grid md:grid-cols-2 gap-8 max-w-4xl mx-auto">
          {plans.map((plan, i) => (
            <StaggerItem key={i}>
              <div className={`relative h-full bg-surface-1 border ${plan.popular ? 'border-accent-blue shadow-lg shadow-accent-blue/10' : 'border-hairline'} rounded-3xl p-8 flex flex-col`}>
                {plan.popular && (
                  <div className="absolute -top-4 left-1/2 -translate-x-1/2 bg-accent-blue text-on-primary text-caption px-4 py-1 rounded-pill uppercase tracking-wider font-bold">
                    Most Popular
                  </div>
                )}
                
                <div className="mb-8">
                  <h3 className="text-display-md text-ink mb-2">{plan.name}</h3>
                  <p className="text-body text-ink-muted h-12">{plan.description}</p>
                  <div className="mt-6 flex items-baseline gap-1">
                    <span className="text-display-lg text-ink">{plan.price}</span>
                    {plan.period && <span className="text-subhead text-ink-muted">{plan.period}</span>}
                  </div>
                </div>

                <div className="flex-1 space-y-4 mb-8">
                  {plan.features.map((feature, j) => (
                    <div key={j} className="flex items-start gap-3">
                      <Check className="w-5 h-5 text-semantic-success shrink-0 mt-0.5" />
                      <span className="text-body text-ink">{feature}</span>
                    </div>
                  ))}
                  {plan.missing.map((feature, j) => (
                    <div key={j} className="flex items-start gap-3 opacity-50">
                      <X className="w-5 h-5 text-ink-muted shrink-0 mt-0.5" />
                      <span className="text-body text-ink-muted">{feature}</span>
                    </div>
                  ))}
                </div>

                {plan.name === "Pro" ? (
                  <Dialog>
                    <DialogTrigger asChild>
                      <Button
                        type="button"
                        variant={plan.buttonVariant as any}
                        className="w-full rounded-pill h-12 bg-primary text-on-primary hover:bg-primary/90"
                      >
                        {plan.buttonText}
                      </Button>
                    </DialogTrigger>
                    <DialogContent className="max-w-lg border border-hairline bg-surface-1 p-6 text-ink">
                      <DialogHeader>
                        <DialogTitle className="text-headline text-ink">
                          Pro is free for now 🎉
                        </DialogTitle>
                        <DialogDescription className="text-body-sm text-ink-muted">
                          Real payment gateway will be added soon. Until then, you can use Pro for free.
                        </DialogDescription>
                      </DialogHeader>

                      <div className="rounded-lg border border-hairline bg-surface-2 p-4 text-center">
                        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-primary/15 text-primary">
                          <Coffee className="h-6 w-6" />
                        </div>
                        <h3 className="text-body font-semibold text-ink">Buy me a coffee</h3>
                        <p className="mx-auto mt-2 max-w-sm text-body-sm text-ink-muted">
                          If InterviewAI helps you, you can support the developer by scanning this QR code with any UPI app.
                        </p>
                        <div className="mx-auto mt-5 h-64 w-64 rounded-lg border border-hairline bg-white bg-contain bg-center bg-no-repeat p-3 shadow-sm" style={{ backgroundImage: `url(${supportQrCodeUrl})` }} aria-label="UPI support QR code" />
                        <div className="mt-4 rounded-md border border-hairline bg-surface-1 p-3">
                          <p className="text-caption text-ink-muted">UPI ID</p>
                          <p className="mt-1 break-all text-body-sm font-semibold text-ink">{supportUpiId}</p>
                        </div>
                      </div>

                      <div className="flex flex-col gap-3 sm:flex-row">
                        <Button asChild className="flex-1 rounded-md bg-primary text-on-primary">
                          <Link href={accountHref}>Continue for Free</Link>
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          className="flex-1 rounded-md border-hairline"
                          onClick={() => void navigator.clipboard?.writeText(supportUpiId)}
                        >
                          <Copy className="mr-2 h-4 w-4" />
                          Copy UPI ID
                        </Button>
                      </div>
                    </DialogContent>
                  </Dialog>
                ) : (
                  <Button
                    asChild
                    variant={plan.buttonVariant as any}
                    className="w-full rounded-pill h-12 border-hairline text-ink hover:bg-surface-2"
                  >
                    <Link href={accountHref}>{plan.buttonText}</Link>
                  </Button>
                )}
              </div>
            </StaggerItem>
          ))}
        </StaggerContainer>
      </div>
    </section>
  );
}
