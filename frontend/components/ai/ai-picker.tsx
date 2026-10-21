"use client";

import { useSyncExternalStore } from "react";
import { ChevronDown, Sparkles } from "lucide-react";
import { AI_CHOICES, getAiChoice, onAiChoiceChange, setAiChoice, type AiChoice } from "@/lib/ai-choice";

/** Small header menu for which AI writes summaries and answers. */
export function AiPicker() {
  const choice = useSyncExternalStore(onAiChoiceChange, getAiChoice, () => "auto" as AiChoice);

  const current = AI_CHOICES.find((option) => option.id === choice) ?? AI_CHOICES[0];

  return (
    <label
      title={`AI: ${current.label}. ${current.hint}.`}
      className="relative inline-flex h-8 items-center gap-1.5 rounded-full border border-border pl-2.5 pr-2 text-xs text-muted-foreground transition-colors focus-within:border-iris/60 hover:border-border-strong hover:text-heading"
    >
      <Sparkles className="size-3.5 text-iris" aria-hidden />
      <span className="sr-only">AI used for summaries and answers</span>
      <span aria-hidden>{current.label}</span>
      <ChevronDown className="size-3.5" aria-hidden />
      <select
        value={choice}
        onChange={(event) => setAiChoice(event.target.value as AiChoice)}
        className="absolute inset-0 cursor-pointer appearance-none opacity-0"
      >
        {AI_CHOICES.map((option) => (
          <option key={option.id} value={option.id}>
            {option.label} ({option.hint})
          </option>
        ))}
      </select>
    </label>
  );
}
