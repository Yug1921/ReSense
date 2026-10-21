"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Copy } from "lucide-react";
import { toast } from "sonner";
import { ApiError, askPaper, type ChatTurn } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { parseBlocks, RichText } from "@/components/reading/rich-text";
import { GlowInput } from "./glow-input";

const STARTERS = [
  "What problem does this paper solve?",
  "What are the main results?",
  "What are its limitations?",
];

interface Message extends ChatTurn {
  sources?: string[];
}

function cleanSection(name: string) {
  if (name.trim().toLowerCase() === "preamble") return "Opening page";
  return name.replace(/^\s*(?:\d+(?:\.\d+)*|[IVX]+)[.)]?\s+/i, "").trim();
}

function errorMessage(err: unknown) {
  if (err instanceof ApiError) {
    if (err.status === 429) return "The free AI models are busy right now. Try again in a minute.";
    if (err.status === 0) return "We couldn't reach ReSense. Check your connection and try again.";
    return err.message;
  }
  return "Something went wrong answering that. Try again.";
}

export function AskPanel({ paperId, initialHistory }: { paperId: string; initialHistory?: ChatTurn[] }) {
  const [messages, setMessages] = useState<Message[]>(initialHistory ?? []);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<{ question: string; message: string } | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (pending) endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, pending]);

  function ask(question: string) {
    const text = question.trim();
    if (!text || pending) return;
    setInput("");
    setError(null);
    setPending(text);
    askPaper(paperId, text)
      .then((res) =>
        setMessages((prev) => [
          ...prev,
          { role: "user", content: text },
          { role: "assistant", content: res.answer, sources: res.used_sections },
        ])
      )
      .catch((err: unknown) => setError({ question: text, message: errorMessage(err) }))
      .finally(() => setPending(null));
  }

  const empty = messages.length === 0 && !pending;

  return (
    <div className="mx-auto flex min-h-[calc(100vh-11rem)] max-w-3xl flex-col">
      <div className="flex flex-1 flex-col gap-7 pb-6">
        {empty && (
          <div className="flex flex-1 flex-col items-center justify-center py-10 text-center">
            <h2 className="text-xl font-semibold">Ask this paper anything</h2>
            <p className="mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">
              Answers are written from the paper&apos;s own text and show which sections they came from.
            </p>
          </div>
        )}

        {messages.map((message, i) =>
          message.role === "user" ? (
            <UserBubble key={i} text={message.content} />
          ) : (
            <Answer key={i} text={message.content} sources={message.sources} />
          )
        )}

        {pending && (
          <>
            <UserBubble text={pending} />
            <div className="flex gap-3.5" role="status" aria-live="polite">
              <AnswerMark />
              <p className="pt-1 text-sm text-muted-foreground">Reading the relevant sections and writing an answer…</p>
            </div>
          </>
        )}

        {error && (
          <div role="alert" className="flex flex-col items-start gap-2 rounded-xl border border-rose/30 bg-rose/10 px-4 py-3">
            <p className="text-sm text-rose">{error.message}</p>
            <Button size="sm" onClick={() => ask(error.question)}>
              Ask again
            </Button>
          </div>
        )}
        <div ref={endRef} />
      </div>

      <div className="sticky bottom-0 -mx-1 bg-gradient-to-t from-background via-background to-background/0 px-1 pb-5 pt-6">
        {messages.length < 6 && !pending && (
          // On phones the suggestions only show before the first question, to keep the answer in view.
          <div className={messages.length ? "mb-3 hidden sm:block" : "mb-3"}>
            <p className="mb-2 text-xs text-subtle-foreground">Try asking</p>
            <div className="flex flex-wrap gap-2">
              {STARTERS.map((starter) => (
                <button
                  key={starter}
                  type="button"
                  onClick={() => ask(starter)}
                  className="rounded-full border border-border bg-card px-3.5 py-1.5 text-[13px] text-foreground transition-colors hover:border-border-strong hover:text-heading"
                >
                  {starter}
                </button>
              ))}
            </div>
          </div>
        )}
        <GlowInput
          value={input}
          onChange={setInput}
          onSubmit={() => ask(input)}
          busy={Boolean(pending)}
          placeholder="Ask anything about this paper…"
        />
      </div>
    </div>
  );
}

function UserBubble({ text }: { text: string }) {
  return (
    <div className="max-w-[85%] self-end whitespace-pre-wrap rounded-2xl rounded-br-md border border-border bg-raised px-4 py-3 text-[15px] leading-relaxed text-heading">
      {text}
    </div>
  );
}

function AnswerMark() {
  return (
    <span aria-hidden className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-iris/12">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-iris">
        <path d="M5 4h9l5 5v11H5z" />
        <path d="M14 4v5h5" />
        <path d="M8.5 14.5l2 2 4-4.5" />
      </svg>
    </span>
  );
}

function Answer({ text, sources }: { text: string; sources?: string[] }) {
  const [copied, setCopied] = useState(false);
  const blocks = parseBlocks(text);
  const sections = Array.from(new Set((sources ?? []).map(cleanSection).filter(Boolean)));

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Couldn't copy. Select the text and copy it instead.");
    }
  }

  return (
    <div className="flex gap-3.5">
      <AnswerMark />
      <div className="min-w-0 flex-1">
        <RichText blocks={blocks} />
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {sections.length > 0 && (
            <>
              <span className="text-xs text-subtle-foreground">From the paper</span>
              {sections.map((section) => (
                <span key={section} className="rounded-full border border-border bg-card px-2.5 py-0.5 text-xs text-muted-foreground">
                  {section}
                </span>
              ))}
            </>
          )}
          <Button size="sm" variant="ghost" onClick={copy} className="ml-auto h-7 px-2 text-xs">
            {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
            {copied ? "Copied" : "Copy"}
          </Button>
        </div>
      </div>
    </div>
  );
}

export default AskPanel;
