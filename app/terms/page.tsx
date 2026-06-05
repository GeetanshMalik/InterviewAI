import { LandingLayout } from "@/layouts/landing-layout";
import { Card } from "@/components/ui/card";
import { FileText, Scale, AlertTriangle, UserCheck } from "lucide-react";

const sections = [
  {
    icon: <UserCheck className="w-6 h-6" />,
    title: "1. Acceptance of Terms",
    content:
      "By accessing and using InterviewAI, you accept and agree to be bound by these Terms of Service. If you do not agree to these terms, please do not use our services. We reserve the right to modify these terms at any time, and your continued use constitutes acceptance of any changes.",
  },
  {
    icon: <FileText className="w-6 h-6" />,
    title: "2. User Accounts",
    content:
      "You must create an account to use our services. You are responsible for maintaining the confidentiality of your account credentials and for all activities under your account. You must provide accurate and complete information during registration and keep your account information updated. You must be at least 13 years old to create an account.",
  },
  {
    icon: <Scale className="w-6 h-6" />,
    title: "3. Acceptable Use",
    content:
      "You agree to use our services only for lawful purposes and in accordance with these Terms. You may not: (a) use our services to violate any laws or regulations; (b) attempt to gain unauthorized access to our systems; (c) interfere with or disrupt our services; (d) share your account with others; (e) use automated tools to access our services without permission; (f) copy, modify, or distribute our content without authorization.",
  },
  {
    icon: <AlertTriangle className="w-6 h-6" />,
    title: "4. Intellectual Property",
    content:
      "All content, features, and functionality of InterviewAI are owned by us and protected by copyright, trademark, and other intellectual property laws. You are granted a limited, non-exclusive, non-transferable license to access and use our services for personal, non-commercial purposes. You retain ownership of the code and content you create using our platform.",
  },
];

const additionalTerms = [
  {
    title: "5. Subscription and Payments",
    points: [
      "Subscription fees are billed in advance on a monthly or annual basis",
      "All fees are non-refundable except as required by law",
      "We reserve the right to change pricing with 30 days notice",
      "You can cancel your subscription at any time from account settings",
      "Access continues until the end of your billing period after cancellation",
    ],
  },
  {
    title: "6. AI-Generated Content",
    points: [
      "AI feedback and evaluations are provided for educational purposes only",
      "We do not guarantee the accuracy or completeness of AI-generated content",
      "AI feedback should not be considered professional career advice",
      "You should verify important information independently",
      "We continuously improve our AI models but cannot guarantee perfection",
    ],
  },
  {
    title: "7. Privacy and Data",
    points: [
      "Your use of our services is subject to our Privacy Policy",
      "We collect and process data as described in our Privacy Policy",
      "You grant us permission to use your data to provide and improve services",
      "We implement security measures to protect your data",
      "You can request data deletion by contacting support",
    ],
  },
  {
    title: "8. Disclaimers and Limitations",
    points: [
      'Services are provided "as is" without warranties of any kind',
      "We do not guarantee uninterrupted or error-free service",
      "We are not liable for any indirect, incidental, or consequential damages",
      "Our total liability is limited to the amount you paid in the last 12 months",
      "Some jurisdictions do not allow liability limitations",
    ],
  },
  {
    title: "9. Termination",
    points: [
      "We may suspend or terminate your account for violations of these Terms",
      "You may terminate your account at any time from settings",
      "Upon termination, your right to use our services ceases immediately",
      "We may retain certain data as required by law or for legitimate purposes",
      "Provisions that should survive termination will remain in effect",
    ],
  },
  {
    title: "10. Governing Law",
    points: [
      "These Terms are governed by the laws of California, United States",
      "Disputes will be resolved in the courts of San Francisco, California",
      "You agree to submit to the jurisdiction of these courts",
      "If any provision is found invalid, the rest remains in effect",
      "These Terms constitute the entire agreement between you and us",
    ],
  },
];

export default function TermsPage() {
  return (
    <LandingLayout>
      <div className="min-h-screen bg-canvas py-20">
        <div className="container mx-auto px-4 max-w-4xl">
          {/* Header */}
          <div className="text-center mb-16">
            <div className="w-16 h-16 rounded-full bg-accent-primary/10 flex items-center justify-center text-accent-primary mx-auto mb-6">
              <Scale className="w-8 h-8" />
            </div>
            <h1 className="text-display-lg text-ink mb-4">Terms of Service</h1>
            <p className="text-body text-ink-muted max-w-2xl mx-auto">
              Last updated: May 13, 2026
            </p>
            <p className="text-body text-ink-muted max-w-2xl mx-auto mt-4">
              Please read these terms carefully before using InterviewAI.
            </p>
          </div>

          {/* Introduction */}
          <Card className="p-8 bg-surface border-hairline-soft mb-8">
            <p className="text-body text-ink-muted leading-relaxed">
              These Terms of Service ("Terms") govern your access to and use of
              InterviewAI's website, services, and applications
              (collectively, the "Services"). By using our Services, you agree
              to be bound by these Terms. If you're using our Services on behalf
              of an organization, you're agreeing to these Terms on behalf of
              that organization.
            </p>
          </Card>

          {/* Main Sections */}
          <div className="space-y-6 mb-8">
            {sections.map((section, index) => (
              <Card
                key={index}
                className="p-6 bg-surface border-hairline-soft hover:border-hairline transition-colors"
              >
                <div className="flex items-start gap-4">
                  <div className="w-12 h-12 rounded-lg bg-accent-primary/10 flex items-center justify-center text-accent-primary flex-shrink-0">
                    {section.icon}
                  </div>
                  <div className="flex-1">
                    <h2 className="text-heading-md text-ink font-bold mb-3">
                      {section.title}
                    </h2>
                    <p className="text-body text-ink-muted leading-relaxed">
                      {section.content}
                    </p>
                  </div>
                </div>
              </Card>
            ))}
          </div>

          {/* Additional Terms */}
          <div className="space-y-6">
            {additionalTerms.map((term, index) => (
              <Card
                key={index}
                className="p-6 bg-surface border-hairline-soft"
              >
                <h2 className="text-heading-md text-ink font-bold mb-4">
                  {term.title}
                </h2>
                <ul className="space-y-2">
                  {term.points.map((point, pointIndex) => (
                    <li
                      key={pointIndex}
                      className="flex items-start gap-3 text-body text-ink-muted"
                    >
                      <span className="text-accent-primary mt-1">•</span>
                      <span>{point}</span>
                    </li>
                  ))}
                </ul>
              </Card>
            ))}
          </div>

          {/* Contact */}
          <Card className="p-8 bg-gradient-to-br from-accent-primary/10 to-accent-secondary/10 border-hairline-soft mt-8 text-center">
            <h3 className="text-heading-lg text-ink font-bold mb-4">
              Questions About These Terms?
            </h3>
            <p className="text-body text-ink-muted mb-6 max-w-2xl mx-auto">
              If you have any questions about these Terms of Service, please
              contact our legal team.
            </p>
            <div className="space-y-2 text-body text-ink-muted">
              <p>Email: legal@interviewai.com</p>
              <p>Address: 123 Innovation Drive, San Francisco, CA 94105</p>
            </div>
          </Card>
        </div>
      </div>
    </LandingLayout>
  );
}
