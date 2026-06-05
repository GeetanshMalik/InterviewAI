export function cleanGeneratedText(value: unknown, fallback = "") {
  const text = String(value ?? "").trim() || fallback;

  return text
    .replace(/\\n/g, "\n")
    .replace(/```(?:\w+)?\n?/g, "")
    .replace(/```/g, "")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/\*\*\*([^*\n]+)\*\*\*/g, "$1")
    .replace(/\*\*([^*\n]+)\*\*/g, "$1")
    .replace(/__([^_\n]+)__/g, "$1")
    .replace(/`([^`\n]+)`/g, "$1")
    .replace(/\*\*/g, "")
    .replace(/__/g, "")
    .replace(/^\s{0,3}#{1,6}\s*/gm, "")
    .split("\n")
    .map((line) => line.replace(/[ \t]+/g, " ").trim())
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}
