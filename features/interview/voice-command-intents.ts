export type VoiceCommand = "dont_know" | "pass" | "repeat" | "paraphrase" | "yes" | "no";

const PASS_COMMAND_PATTERNS = [
  /\b(proceed|continue)\s+(to\s+)?(the\s+)?next\s+(question|one)\b/gi,
  /\b(next|another|new|different)\s+(question|one)\b/gi,
  /\b(ask|give)\s+(me\s+)?(another|a different|the next|next)\b/gi,
  /\b(move|go|carry)\s+(on|ahead|forward)\b/gi,
  /\blet'?s\s+(move|go)\s+on\b/gi,
  /\b(skip|pass)\s+(this|it|question|one)?\b/gi,
  /\b(i\s+)?(can't|cannot|cant|couldn't|could not|unable|not able)\s+(answer|solve|do|attempt|figure|continue)(\s+(this|it|question|one))?\b/gi,
  /\b(i\s+)?(don't|do not|dont)\s+know\b/gi,
  /\bchange\s+(the\s+)?question\b/gi,
];

const DONT_KNOW_PATTERNS = [
  /\b(i\s+)?(don't|do not|dont)\s+know(\s+(the\s+)?answer)?\b/gi,
  /\b(no\s+idea|not\s+sure|i\s+am\s+not\s+sure|i'm\s+not\s+sure)\b/gi,
  /\b(i\s+)?(can't|cannot|cant|couldn't|could not|unable|not able)\s+(answer|solve|do|attempt|figure)(\s+(this|it|question|one))?\b/gi,
];

export function answerTextWithoutPassCommand(text: string) {
  let cleaned = text;
  PASS_COMMAND_PATTERNS.forEach((pattern) => {
    cleaned = cleaned.replace(pattern, " ");
  });
  DONT_KNOW_PATTERNS.forEach((pattern) => {
    cleaned = cleaned.replace(pattern, " ");
  });
  cleaned = cleaned.replace(/\b(next|pass|skip|proceed|continue)\b/gi, " ");
  cleaned = cleaned.replace(/[^\w\s']/g, " ").replace(/\s+/g, " ").trim();
  return cleaned;
}

export function isSubstantiveAnswerText(text: string) {
  const cleaned = text
    .toLowerCase()
    .replace(/\b(please|plz|okay|ok|sir|ma'?am|mam|thanks|thank you|um|uh|hmm)\b/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return cleaned.split(" ").filter(Boolean).length >= 3;
}

export function commandFromSpeech(text: string): VoiceCommand | null {
  const normalized = text.toLowerCase().replace(/[^\w\s']/g, " ").replace(/\s+/g, " ").trim();
  const words = normalized.split(" ").filter(Boolean);
  const short = words.length <= 10;
  const commandLength = words.length <= 16;

  if (
    commandLength &&
    DONT_KNOW_PATTERNS.some((pattern) => {
      pattern.lastIndex = 0;
      return pattern.test(normalized);
    })
  ) {
    return "dont_know";
  }

  if (
    commandLength &&
    (PASS_COMMAND_PATTERNS.some((pattern) => {
      pattern.lastIndex = 0;
      return pattern.test(normalized);
    }) ||
      (words.length <= 4 && /\b(next|pass|skip)\b/.test(normalized)) ||
      false)
  ) {
    return "pass";
  }

  if (!short) return null;
  if (/\b(repeat|say again|again|come again|can you repeat)\b/.test(normalized)) return "repeat";
  if (/\b(paraphrase|explain|rephrase|simpler|simplify|make it easier)\b/.test(normalized)) return "paraphrase";
  if (/\b(yes|yeah|yep|sure|start|begin|ready|let's start|lets start)\b/.test(normalized)) return "yes";
  if (/\b(no|not yet|wait|hold on|pause)\b/.test(normalized)) return "no";
  return null;
}
