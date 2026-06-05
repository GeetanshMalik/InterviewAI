export type InterviewVoiceProfile = {
  value: string;
  label: string;
  accent: string;
  lang: string;
  voiceNameHints: string[];
  rate: number;
  pitch: number;
};

export const interviewVoiceProfiles: InterviewVoiceProfile[] = [
  {
    value: "en-IN-female-1",
    label: "Indian English Female 1",
    accent: "Indian English",
    lang: "en-IN",
    voiceNameHints: ["heera", "kalpana", "raveena", "female", "india", "indian"],
    rate: 0.9,
    pitch: 1.02,
  },
  {
    value: "en-IN-female-2",
    label: "Indian English Female 2",
    accent: "Indian English",
    lang: "en-IN",
    voiceNameHints: ["veena", "priya", "female", "india", "indian"],
    rate: 0.88,
    pitch: 1.06,
  },
  {
    value: "en-IN-female-3",
    label: "Indian English Female 3",
    accent: "Indian English",
    lang: "en-IN",
    voiceNameHints: ["neerja", "swara", "female", "india", "indian"],
    rate: 0.92,
    pitch: 1,
  },
  {
    value: "en-US-female-1",
    label: "US English Female 1",
    accent: "US English",
    lang: "en-US",
    voiceNameHints: ["zira", "jenny", "aria", "samantha", "female", "united states"],
    rate: 0.94,
    pitch: 1,
  },
  {
    value: "en-US-female-2",
    label: "US English Female 2",
    accent: "US English",
    lang: "en-US",
    voiceNameHints: ["michelle", "monica", "sara", "female", "united states"],
    rate: 0.9,
    pitch: 1.04,
  },
];

export const defaultInterviewVoiceProfile = "en-IN-female-1";

export function getInterviewVoiceProfile(value?: string) {
  return (
    interviewVoiceProfiles.find((profile) => profile.value === value) ||
    interviewVoiceProfiles.find((profile) => profile.value === defaultInterviewVoiceProfile)!
  );
}
