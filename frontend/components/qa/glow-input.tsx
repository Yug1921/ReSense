"use client";

import { useLayoutEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { ArrowUp, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

const MAX_HEIGHT = 168; // about six lines, then it scrolls

/**
 * The ReSense question box. Its signature glow follows the text cursor while
 * you type (kept from the original design, recoloured to the Iris accent).
 * The caret position is measured with a hidden mirror of the text, so the
 * glow tracks it across wrapped lines too.
 */
export function GlowInput({
  value,
  onChange,
  onSubmit,
  placeholder,
  busy,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  placeholder: string;
  busy?: boolean;
}) {
  const [focused, setFocused] = useState(false);
  const [caret, setCaret] = useState({ x: 24, y: 24 });
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const beforeRef = useRef<HTMLSpanElement>(null);
  const markerRef = useRef<HTMLSpanElement>(null);

  function measureCaret() {
    const textarea = textareaRef.current;
    const before = beforeRef.current;
    const marker = markerRef.current;
    if (!textarea || !before || !marker) return;
    before.textContent = textarea.value.slice(0, textarea.selectionStart ?? 0);
    setCaret({
      x: marker.offsetLeft,
      y: marker.offsetTop - textarea.scrollTop + marker.offsetHeight / 2,
    });
  }

  // Grow with the text, up to MAX_HEIGHT.
  useLayoutEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, MAX_HEIGHT)}px`;
  }, [value]);

  function submit(event?: FormEvent) {
    event?.preventDefault();
    if (!busy && value.trim()) onSubmit();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  }

  const glow = (radius: number, alpha: number) =>
    `radial-gradient(circle ${radius}px at ${caret.x}px ${caret.y}px, rgba(156, 165, 234, ${alpha}), transparent 70%)`;

  return (
    <form onSubmit={submit} className="relative w-full">
      <div
        aria-hidden
        className={cn(
          "pointer-events-none absolute -inset-px rounded-2xl transition-opacity duration-300",
          focused ? "opacity-100" : "opacity-0"
        )}
        style={{ background: glow(140, 0.28) }}
      />
      <div
        className={cn(
          "relative overflow-hidden rounded-2xl border bg-card transition-colors",
          focused ? "border-iris/40" : "border-border"
        )}
      >
        <div
          aria-hidden
          className={cn("pointer-events-none absolute inset-0 transition-opacity duration-300", focused ? "opacity-100" : "opacity-0")}
          style={{ background: glow(120, 0.1) }}
        />
        <textarea
          ref={textareaRef}
          rows={1}
          value={value}
          aria-label="Ask a question about this paper"
          placeholder={placeholder}
          onChange={(event) => {
            onChange(event.target.value);
            requestAnimationFrame(measureCaret);
          }}
          onKeyDown={handleKeyDown}
          onKeyUp={measureCaret}
          onClick={measureCaret}
          onScroll={measureCaret}
          onFocus={() => {
            setFocused(true);
            requestAnimationFrame(measureCaret);
          }}
          onBlur={() => setFocused(false)}
          className="relative block w-full resize-none bg-transparent px-5 pb-1 pt-4 text-[15px] leading-6 text-heading outline-none placeholder:text-subtle-foreground"
        />
        <div
          aria-hidden
          className="pointer-events-none invisible absolute left-0 top-0 w-full whitespace-pre-wrap break-words px-5 pt-4 text-[15px] leading-6"
        >
          <span ref={beforeRef} />
          <span ref={markerRef}>&#8203;</span>
        </div>
        <div className="relative flex items-center justify-between gap-3 px-5 pb-3 pt-1">
          <span className="text-xs text-subtle-foreground">
            Answers come only from this paper&apos;s text.
            <span className="hidden sm:inline"> Enter to send, Shift + Enter for a new line.</span>
          </span>
          <button
            type="submit"
            disabled={busy || !value.trim()}
            aria-label="Send question"
            className="inline-flex size-8 shrink-0 items-center justify-center rounded-lg bg-iris text-iris-ink transition-colors hover:bg-iris-strong disabled:bg-raised disabled:text-subtle-foreground"
          >
            {busy ? (
              <Loader2 className="size-4 animate-spin" aria-hidden />
            ) : (
              <ArrowUp className="size-4" strokeWidth={2.25} aria-hidden />
            )}
          </button>
        </div>
      </div>
    </form>
  );
}
