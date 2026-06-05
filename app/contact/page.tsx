import { LandingLayout } from "@/layouts/landing-layout";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Mail, MessageSquare, Phone, MapPin } from "lucide-react";

export default function ContactPage() {
  return (
    <LandingLayout>
      <div className="min-h-screen bg-canvas py-20">
        <div className="container mx-auto px-4 max-w-6xl">
          {/* Header */}
          <div className="text-center mb-16">
            <h1 className="text-display-lg text-ink mb-4">Get in Touch</h1>
            <p className="text-body text-ink-muted max-w-2xl mx-auto">
              Questions, product feedback, or account help can start here. The
              best path today is email or the message form below.
            </p>
          </div>

          <div className="grid lg:grid-cols-3 gap-8">
            {/* Contact Info */}
            <div className="space-y-6">
              <Card className="p-6 bg-surface border-hairline-soft">
                <div className="w-12 h-12 rounded-lg bg-accent-primary/10 flex items-center justify-center text-accent-primary mb-4">
                  <Mail className="w-6 h-6" />
                </div>
                <h3 className="text-heading-sm text-ink font-bold mb-2">
                  Email Us
                </h3>
                <p className="text-body text-ink-muted mb-2">
                  Our team is here to help
                </p>
                <a
                  href="mailto:support@interviewai.com"
                  className="text-body text-accent-primary hover:underline"
                >
                  support@interviewai.com
                </a>
              </Card>

              <Card className="p-6 bg-surface border-hairline-soft">
                <div className="w-12 h-12 rounded-lg bg-accent-primary/10 flex items-center justify-center text-accent-primary mb-4">
                  <MessageSquare className="w-6 h-6" />
                </div>
                <h3 className="text-heading-sm text-ink font-bold mb-2">
                  AI Bot Help
                </h3>
                <p className="text-body text-ink-muted mb-2">
                  Ask the in-app consultant about reports, roadmaps, and next steps
                </p>
                <p className="text-caption text-ink-muted">
                  Available from the workspace after sign in
                </p>
              </Card>

              <Card className="p-6 bg-surface border-hairline-soft">
                <div className="w-12 h-12 rounded-lg bg-accent-primary/10 flex items-center justify-center text-accent-primary mb-4">
                  <Phone className="w-6 h-6" />
                </div>
                <h3 className="text-heading-sm text-ink font-bold mb-2">
                  Product Feedback
                </h3>
                <p className="text-body text-ink-muted mb-2">
                  Share bugs, missing features, or workflow issues
                </p>
                <p className="text-caption text-ink-muted">We review product feedback during roadmap planning.</p>
              </Card>

              <Card className="p-6 bg-surface border-hairline-soft">
                <div className="w-12 h-12 rounded-lg bg-accent-primary/10 flex items-center justify-center text-accent-primary mb-4">
                  <MapPin className="w-6 h-6" />
                </div>
                <h3 className="text-heading-sm text-ink font-bold mb-2">
                  Company
                </h3>
                <p className="text-body text-ink-muted">
                  InterviewAI is built around backend-owned, multi-agent interview preparation.
                </p>
              </Card>
            </div>

            {/* Contact Form */}
            <div className="lg:col-span-2">
              <Card className="p-8 bg-surface border-hairline-soft">
                <h2 className="text-heading-lg text-ink font-bold mb-6">
                  Send us a Message
                </h2>
                <form className="space-y-6">
                  <div className="grid md:grid-cols-2 gap-6">
                    <div className="space-y-2">
                      <Label htmlFor="firstName">First Name</Label>
                      <Input
                        id="firstName"
                        placeholder="John"
                        className="bg-canvas"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="lastName">Last Name</Label>
                      <Input
                        id="lastName"
                        placeholder="Doe"
                        className="bg-canvas"
                      />
                    </div>
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="email">Email</Label>
                    <Input
                      id="email"
                      type="email"
                      placeholder="john@example.com"
                      className="bg-canvas"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="subject">Subject</Label>
                    <Select>
                      <SelectTrigger className="bg-canvas">
                        <SelectValue placeholder="Select a subject" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="general">General Inquiry</SelectItem>
                        <SelectItem value="support">
                          Technical Support
                        </SelectItem>
                        <SelectItem value="billing">
                          Billing Question
                        </SelectItem>
                        <SelectItem value="feature">
                          Feature Request
                        </SelectItem>
                        <SelectItem value="partnership">
                          Partnership Opportunity
                        </SelectItem>
                        <SelectItem value="other">Other</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="message">Message</Label>
                    <Textarea
                      id="message"
                      placeholder="Tell us how we can help you..."
                      rows={6}
                      className="bg-canvas resize-none"
                    />
                  </div>

                  <Button type="submit" size="lg" className="w-full">
                    Send Message
                  </Button>
                </form>
              </Card>
            </div>
          </div>
        </div>
      </div>
    </LandingLayout>
  );
}
