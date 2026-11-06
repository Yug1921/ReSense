// Which AI the app uses, picked from the header menu. Saved in this browser
// only and sent with each request; "auto" lets the server pick the best
// available model and fall back across providers.
export const AI_CHOICES = [
  { id: "auto", label: "Automatic", hint: "Best available, with fallback" },
  { id: "gemini", label: "Gemini", hint: "Best quality" },
  { id: "groq", label: "Groq", hint: "Fastest, short tasks only" },
  { id: "openrouter", label: "OpenRouter", hint: "Free test models" },
] as const;

export type AiChoice = (typeof AI_CHOICES)[number]["id"];

const STORAGE_KEY = "resense-ai";
const EVENT = "resense-ai-change";

export function getAiChoice(): AiChoice {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    if (AI_CHOICES.some((choice) => choice.id === value)) return value as AiChoice;
  } catch {
    // storage unavailable (private window): fall through to the default
  }
  return "auto";
}

export function setAiChoice(choice: AiChoice) {
  try {
    window.localStorage.setItem(STORAGE_KEY, choice);
  } catch {
    // not saved, but still used for this page
  }
  window.dispatchEvent(new CustomEvent(EVENT, { detail: choice }));
}

export function onAiChoiceChange(listener: (choice: AiChoice) => void) {
  const handler = (event: Event) => listener((event as CustomEvent<AiChoice>).detail);
  window.addEventListener(EVENT, handler);
  return () => window.removeEventListener(EVENT, handler);
}
