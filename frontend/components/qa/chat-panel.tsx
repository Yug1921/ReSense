"use client";

import { useRef, useState, type FormEvent } from "react";
import { motion, AnimatePresence } from "motion/react";
import { Send, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { askPaper, ApiError } from "@/lib/api";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  usedSections?: string[];
}

/**
 * Same glow-follows-cursor mechanic and color as the original hero-scale
 * template — untouched on purpose, per instruction that this animation is
 * the USP. Only the scale changed: text-5xl/py-8 hero input down to a
 * normal chat-input size (text-base/py-3), with the glow radius and cursor
 * offset scaled down to match proportionally.
 */
function GlowingChatInput({
  value,
  onChange,
  onSubmit,
  placeholder,
  disabled,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  placeholder: string;
  disabled?: boolean;
}) {
  const [isFocused, setIsFocused] = useState(false);
  const [cursorPosition, setCursorPosition] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const measureRef = useRef<HTMLSpanElement>(null);

  function updateCursorPosition() {
    if (measureRef.current && inputRef.current) {
      const textBeforeCursor = value.slice(0, inputRef.current.selectionStart || 0);
      measureRef.current.textContent = textBeforeCursor || " ";
      setCursorPosition(measureRef.current.offsetWidth);
    }
  }

  return (
    <form
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        if (!disabled && value.trim()) onSubmit();
      }}
      className="relative w-full"
    >
      <div
        className={cn(
          "pointer-events-none absolute inset-0 rounded-2xl transition-opacity duration-300",
          isFocused ? "opacity-100" : "opacity-0"
        )}
        style={{
          background: `radial-gradient(circle 120px at ${cursorPosition + 24}px 50%, rgba(180, 255, 120, 0.15), transparent 70%)`,
        }}
      />

      <div className="relative overflow-hidden rounded-2xl border border-white/10 bg-[#1a2332]/50 backdrop-blur-sm">
        <div
          className={cn(
            "pointer-events-none absolute inset-0 transition-opacity duration-300",
            isFocused ? "opacity-100" : "opacity-0"
          )}
          style={{
            background: `radial-gradient(circle 110px at ${cursorPosition + 24}px 50%, rgba(200, 255, 140, 0.12), transparent 60%)`,
          }}
        />

        <input
          ref={inputRef}
          type="text"
          value={value}
          disabled={disabled}
          onChange={(e) => {
            onChange(e.target.value);
            requestAnimationFrame(updateCursorPosition);
          }}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          onClick={updateCursorPosition}
          onKeyUp={updateCursorPosition}
          placeholder={placeholder}
          className={cn(
            "relative w-full bg-transparent px-5 py-3 pr-12 text-base font-light text-white",
            "placeholder:text-white/40 focus:outline-none",
            "disabled:cursor-not-allowed disabled:opacity-60"
          )}
          style={{ caretColor: "white" }}
        />

        <button
          type="submit"
          disabled={disabled || !value.trim()}
          className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full p-2 text-white/60 transition-colors hover:bg-white/10 hover:text-white disabled:opacity-30"
          aria-label="Send question"
        >
          {disabled ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
        </button>

        <span
          ref={measureRef}
          className="pointer-events-none absolute left-5 top-3 whitespace-pre text-base font-light opacity-0"
          aria-hidden="true"
        >
          {" "}
        </span>
      </div>
    </form>
  );
}

export interface ChatPanelProps {
  paperId: string;
  className?: string;
}

export function ChatPanel({ paperId, className }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleSend() {
    const question = input.trim();
    if (!question || isSending) return;

    setMessages((prev) => [...prev, { role: "user", content: question }]);
    setInput("");
    setError(null);
    setIsSending(true);

    askPaper(paperId, question)
      .then((res) => {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: res.answer, usedSections: res.used_sections },
        ]);
      })
      .catch((err: unknown) => {
        const message = err instanceof ApiError ? err.message : "Something went wrong answering that.";
        setError(message);
      })
      .finally(() => setIsSending(false));
  }

  return (
    <div className={cn("flex w-full flex-col gap-4", className)}>
      <div className="flex flex-col gap-3">
        <AnimatePresence initial={false}>
          {messages.map((msg, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              className={cn("flex", msg.role === "user" ? "justify-end" : "justify-start")}
            >
              <div
                className={cn(
                  "max-w-[80%] rounded-xl px-4 py-2.5 text-sm leading-relaxed",
                  msg.role === "user"
                    ? "bg-blue-500 text-white"
                    : "border border-white/10 bg-white/[0.03] text-zinc-200"
                )}
              >
                <p className="whitespace-pre-wrap">{msg.content}</p>
                {msg.usedSections && msg.usedSections.length > 0 && (
                  <p className="mt-2 text-xs text-muted-foreground">
                    Source: {msg.usedSections.join(", ")}
                  </p>
                )}
              </div>
            </motion.div>
          ))}
        </AnimatePresence>

        {isSending && (
          <div className="flex justify-start">
            <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-2.5 text-sm text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Thinking…
            </div>
          </div>
        )}
      </div>

      {error && <p className="text-sm text-red-400">{error}</p>}

      <GlowingChatInput
        value={input}
        onChange={setInput}
        onSubmit={handleSend}
        disabled={isSending}
        placeholder="Ask something about this paper…"
      />
    </div>
  );
}

export default ChatPanel;