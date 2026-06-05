"use client";

import { InterviewTabs } from "@/features/interview/interview-tabs";
import { FormTab } from "@/features/interview/form-tab";
import { AptitudeTab } from "@/features/interview/aptitude-tab";
import { DSATab } from "@/features/interview/dsa-tab";
import { TechnicalTab } from "@/features/interview/technical-tab";
import { HRTab } from "@/features/interview/hr-tab";

export default function InterviewPage() {
  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <div className="shrink-0 pb-4">
        <h1 className="mb-1 text-display-md text-ink">New Interview</h1>
        <p className="text-body-sm text-ink-muted">
          Complete all rounds to receive your comprehensive interview report
        </p>
      </div>

      <InterviewTabs>
        {{
          form: <FormTab />,
          dsa: <DSATab />,
          aptitude: <AptitudeTab />,
          technical: <TechnicalTab />,
          hr: <HRTab />,
        }}
      </InterviewTabs>
    </div>
  );
}
