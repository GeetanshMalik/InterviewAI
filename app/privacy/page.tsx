import { LandingLayout } from "@/layouts/landing-layout";
import { Card } from "@/components/ui/card";
import { Shield, Lock, Eye, UserCheck, Database, FileText } from "lucide-react";

const sections = [
  {
    icon: <FileText className="w-6 h-6" />,
    title: "Information We Collect",
    content: [
      "Account information (name, email, password)",
      "Profile data (skills, experience, preferences)",
      "Interview session data (code, responses, performance metrics)",
      "Usage data (features used, time spent, interaction patterns)",
      "Device and browser information",
      "Cookies and similar tracking technologies",
    ],
  },
  {
    icon: <Database className="w-6 h-6" />,
    title: "How We Use Your Information",
    content: [
      "Provide and improve our interview preparation services",
      "Generate personalized AI feedback and recommendations",
      "Analyze performance trends and create learning roadmaps",
      "Send important updates and notifications",
      "Ensure platform security and prevent fraud",
      "Comply with legal obligations",
    ],
  },
  {
    icon: <Lock className="w-6 h-6" />,
    title: "Data Security",
    content: [
      "Industry-standard encryption for data in transit and at rest",
      "Regular security audits and penetration testing",
      "Secure data centers with 24/7 monitoring",
      "Access controls and authentication mechanisms",
      "Regular backups and disaster recovery procedures",
      "Employee training on data protection practices",
    ],
  },
  {
    icon: <Eye className="w-6 h-6" />,
    title: "Data Sharing",
    content: [
      "We do NOT sell your personal information to third parties",
      "Service providers (hosting, analytics) under strict agreements",
      "Legal requirements (court orders, regulatory compliance)",
      "Business transfers (mergers, acquisitions) with notice",
      "With your explicit consent for specific purposes",
    ],
  },
  {
    icon: <UserCheck className="w-6 h-6" />,
    title: "Your Rights",
    content: [
      "Access your personal data at any time",
      "Request correction of inaccurate information",
      "Delete your account and associated data",
      "Export your data in a portable format",
      "Opt-out of marketing communications",
      "Object to certain data processing activities",
    ],
  },
  {
    icon: <Shield className="w-6 h-6" />,
    title: "Data Retention",
    content: [
      "Active account data: retained while account is active",
      "Interview sessions: retained for 2 years for analytics",
      "Performance reports: retained for 3 years",
      "Deleted account data: permanently removed within 30 days",
      "Legal compliance data: retained as required by law",
      "Anonymized data: may be retained indefinitely for research",
    ],
  },
];

export default function PrivacyPage() {
  return (
    <LandingLayout>
      <div className="min-h-screen bg-canvas py-20">
        <div className="container mx-auto px-4 max-w-4xl">
          {/* Header */}
          <div className="text-center mb-16">
            <div className="w-16 h-16 rounded-full bg-accent-primary/10 flex items-center justify-center text-accent-primary mx-auto mb-6">
              <Shield className="w-8 h-8" />
            </div>
            <h1 className="text-display-lg text-ink mb-4">Privacy Policy</h1>
            <p className="text-body text-ink-muted max-w-2xl mx-auto">
              Last updated: May 13, 2026
            </p>
            <p className="text-body text-ink-muted max-w-2xl mx-auto mt-4">
              Your privacy is important to us. This policy explains how we
              collect, use, and protect your personal information.
            </p>
          </div>

          {/* Introduction */}
          <Card className="p-8 bg-surface border-hairline-soft mb-8">
            <p className="text-body text-ink-muted leading-relaxed">
              InterviewAI ("we," "our," or "us") is committed to protecting
              your privacy. This Privacy Policy explains how we collect, use,
              disclose, and safeguard your information when you use our
              platform. By using InterviewAI, you agree to the collection and
              use of information in accordance with this policy.
            </p>
          </Card>

          {/* Sections */}
          <div className="space-y-6">
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
                    <h2 className="text-heading-md text-ink font-bold mb-4">
                      {section.title}
                    </h2>
                    <ul className="space-y-2">
                      {section.content.map((item, itemIndex) => (
                        <li
                          key={itemIndex}
                          className="flex items-start gap-3 text-body text-ink-muted"
                        >
                          <span className="text-accent-primary mt-1">•</span>
                          <span>{item}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              </Card>
            ))}
          </div>

          {/* International Users */}
          <Card className="p-8 bg-surface border-hairline-soft mt-8">
            <h2 className="text-heading-md text-ink font-bold mb-4">
              International Users
            </h2>
            <p className="text-body text-ink-muted leading-relaxed mb-4">
              If you are accessing our services from outside the United States,
              please be aware that your information may be transferred to,
              stored, and processed in the United States where our servers are
              located. By using our services, you consent to this transfer.
            </p>
            <p className="text-body text-ink-muted leading-relaxed">
              We comply with applicable data protection laws including GDPR
              (European Union), CCPA (California), and other regional privacy
              regulations.
            </p>
          </Card>

          {/* Children's Privacy */}
          <Card className="p-8 bg-surface border-hairline-soft mt-8">
            <h2 className="text-heading-md text-ink font-bold mb-4">
              Children's Privacy
            </h2>
            <p className="text-body text-ink-muted leading-relaxed">
              Our services are not intended for users under the age of 13. We do
              not knowingly collect personal information from children under 13.
              If you are a parent or guardian and believe your child has
              provided us with personal information, please contact us
              immediately.
            </p>
          </Card>

          {/* Changes to Policy */}
          <Card className="p-8 bg-surface border-hairline-soft mt-8">
            <h2 className="text-heading-md text-ink font-bold mb-4">
              Changes to This Policy
            </h2>
            <p className="text-body text-ink-muted leading-relaxed">
              We may update this Privacy Policy from time to time. We will
              notify you of any changes by posting the new policy on this page
              and updating the "Last updated" date. You are advised to review
              this policy periodically for any changes.
            </p>
          </Card>

          {/* Contact */}
          <Card className="p-8 bg-gradient-to-br from-accent-primary/10 to-accent-secondary/10 border-hairline-soft mt-8 text-center">
            <h3 className="text-heading-lg text-ink font-bold mb-4">
              Questions About Privacy?
            </h3>
            <p className="text-body text-ink-muted mb-6 max-w-2xl mx-auto">
              If you have any questions about this Privacy Policy or our data
              practices, please contact us.
            </p>
            <div className="space-y-2 text-body text-ink-muted">
              <p>Email: privacy@interviewai.com</p>
              <p>Address: 123 Innovation Drive, San Francisco, CA 94105</p>
            </div>
          </Card>
        </div>
      </div>
    </LandingLayout>
  );
}
