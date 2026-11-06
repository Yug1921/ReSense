"use client";

import { useEffect, useId, useRef, useState, useSyncExternalStore, type KeyboardEvent } from "react";
import { Check, ChevronDown, Sparkles } from "lucide-react";
import { AI_CHOICES, getAiChoice, onAiChoiceChange, setAiChoice, type AiChoice } from "@/lib/ai-choice";
import { cn } from "@/lib/utils";

/** Small header menu for which AI writes summaries and answers. */
export function AiPicker() {
  const choice = useSyncExternalStore(onAiChoiceChange, getAiChoice, () => "auto" as AiChoice);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const listId = useId();

  const currentIndex = Math.max(0, AI_CHOICES.findIndex((option) => option.id === choice));
  const current = AI_CHOICES[currentIndex];

  useEffect(() => {
    if (!open) return;
    function close(event: MouseEvent) {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  function openMenu() {
    setActive(currentIndex);
    setOpen(true);
  }

  function pick(index: number) {
    setAiChoice(AI_CHOICES[index].id);
    setOpen(false);
    buttonRef.current?.focus();
  }

  function handleKeys(event: KeyboardEvent<HTMLDivElement>) {
    if (!open) {
      if (["ArrowDown", "ArrowUp", "Enter", " "].includes(event.key)) {
        event.preventDefault();
        openMenu();
      }
      return;
    }
    if (event.key === "Escape" || event.key === "Tab") {
      setOpen(false);
      if (event.key === "Escape") buttonRef.current?.focus();
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((index) => (index + step + AI_CHOICES.length) % AI_CHOICES.length);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      pick(active);
    }
  }

  return (
    <div ref={containerRef} className="relative" onKeyDown={handleKeys}>
      <button
        ref={buttonRef}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-label={`AI used for summaries and answers: ${current.label}`}
        onClick={() => (open ? setOpen(false) : openMenu())}
        className={cn(
          "inline-flex h-8 items-center gap-1.5 rounded-full border pl-2.5 pr-2 text-xs transition-colors",
          open
            ? "border-iris/60 text-heading"
            : "border-border text-muted-foreground hover:border-border-strong hover:text-heading"
        )}
      >
        <Sparkles className="size-3.5 text-iris" aria-hidden />
        <span className="hidden sm:inline">{current.label}</span>
        <ChevronDown
          className={cn("size-3.5 transition-transform duration-200", open && "rotate-180")}
          aria-hidden
        />
      </button>

      {open && (
        <div
          id={listId}
          role="listbox"
          aria-label="AI used for summaries and answers"
          aria-activedescendant={`${listId}-${active}`}
          className="absolute right-0 top-full z-50 mt-2 w-72 origin-top-right animate-pop-in overflow-hidden rounded-xl border border-border bg-raised p-1 shadow-lg shadow-shadow"
        >
          <p className="px-3 pb-1.5 pt-2 text-[11px] font-medium uppercase tracking-[0.06em] text-subtle-foreground">
            AI for summaries and answers
          </p>
          {AI_CHOICES.map((option, index) => {
            const selected = option.id === choice;
            return (
              <div
                key={option.id}
                id={`${listId}-${index}`}
                role="option"
                aria-selected={selected}
                onMouseEnter={() => setActive(index)}
                onClick={() => pick(index)}
                className={cn(
                  "flex cursor-pointer items-start gap-2.5 rounded-lg px-3 py-2 transition-colors duration-150",
                  index === active ? "bg-card" : ""
                )}
              >
                <span className="min-w-0 flex-1">
                  <span className={cn("block text-sm", selected ? "text-heading" : "text-foreground")}>
                    {option.label}
                  </span>
                  <span className="block text-xs text-subtle-foreground">{option.hint}</span>
                </span>
                <Check
                  aria-hidden
                  className={cn("mt-0.5 size-4 shrink-0 text-iris transition-opacity", selected ? "opacity-100" : "opacity-0")}
                />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
