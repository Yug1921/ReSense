"use client";

import { useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Check, Copy, RotateCw } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { ApiError, summarizePaper, TONES, type Tone } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { parseBlocks, RichText } from "@/components/reading/rich-text";

const RECOMMENDED: Tone = "research_insight";

function errorMessage(err: unknown) {
  if (err instanceof ApiError) {
    if (err.status === 429) return "The free AI models are busy right now. Try again in a minute.";
    if (err.status === 502 || err.status === 503) return "The AI service is unavailable right now. Try again shortly.";
    if (err.status === 0) return "We couldn't reach ReSense. Check your connection and try again.";
    return err.message;
  }
  return "Something went wrong writing this summary. Try again.";
}

export interface SummaryPanelProps {
  paperId: string;
  initialSummaries?: Partial<Record<Tone, string>>;
}

export function SummaryPanel({ paperId, initialSummaries }: SummaryPanelProps) {
  const [tone, setTone] = useState<Tone>(RECOMMENDED);
  const [summaries, setSummaries] = useState<Partial<Record<Tone, string>>>(initialSummaries ?? {});
  const [writing, setWriting] = useState<Tone | null>(null);
  const [errors, setErrors] = useState<Partial<Record<Tone, string>>>({});
  const [copied, setCopied] = useState(false);
  const cardRefs = useRef<Partial<Record<Tone, HTMLButtonElement | null>>>({});

  const content = summaries[tone];
  const blocks = useMemo(() => (content ? parseBlocks(content) : []), [content]);
  const headings = blocks.filter((b) => b.kind === "heading");
  const meta = TONES.find((t) => t.id === tone)!;

  function write(target: Tone, refresh = false) {
    if (writing) return;
    setWriting(target);
    setErrors((prev) => ({ ...prev, [target]: undefined }));
    summarizePaper(paperId, target, refresh)
      .then((res) => setSummaries((prev) => ({ ...prev, [target]: res.content })))
      .catch((err: unknown) => setErrors((prev) => ({ ...prev, [target]: errorMessage(err) })))
      .finally(() => setWriting(null));
  }

  // Picking a tone is the request: show it if it's written, otherwise write it.
  function choose(target: Tone) {
    setTone(target);
    setCopied(false);
    if (!summaries[target] && writing !== target) write(target);
  }

  function handleKeys(event: KeyboardEvent<HTMLDivElement>) {
    const index = TONES.findIndex((t) => t.id === tone);
    const step = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const next = TONES[(index + step + TONES.length) % TONES.length].id;
    setTone(next);
    cardRefs.current[next]?.focus();
  }

  async function copy() {
    if (!content) return;
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Couldn't copy. Select the text and copy it instead.");
    }
  }

  const isWriting = writing === tone;
  const error = errors[tone];

  return (
    <div className="flex flex-col gap-6">
      <div>
        <p id="tone-label" className="mb-2.5 text-[13px] text-muted-foreground">
          Choose how you want it written
        </p>
        <div
          role="radiogroup"
          aria-labelledby="tone-label"
          onKeyDown={handleKeys}
          className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-5"
        >
          {TONES.map((t) => {
            const selected = t.id === tone;
            const ready = Boolean(summaries[t.id]);
            return (
              <button
                key={t.id}
                ref={(node) => {
                  cardRefs.current[t.id] = node;
                }}
                type="button"
                role="radio"
                aria-checked={selected}
                tabIndex={selected ? 0 : -1}
                onClick={() => choose(t.id)}
                className={cn(
                  "flex flex-col items-start gap-1 rounded-xl border p-3.5 text-left transition-colors",
                  selected ? "border-iris/55 bg-iris/10" : "border-border bg-card hover:border-border-strong"
                )}
              >
                <span className="flex w-full items-center justify-between gap-2">
                  <span className={cn("text-sm font-medium", selected ? "text-heading" : "text-foreground")}>{t.label}</span>
                  {ready ? (
                    <Check className="size-3.5 shrink-0 text-sage" aria-label="Written" />
                  ) : writing === t.id ? (
                    <span className="size-1.5 shrink-0 animate-pulse rounded-full bg-iris" aria-label="Writing" />
                  ) : null}
                </span>
                <span className={cn("text-xs leading-snug", selected ? "text-muted-foreground" : "text-subtle-foreground")}>
                  {t.description}
                </span>
                {t.id === RECOMMENDED && (
                  <Badge tone="iris" className="mt-1">
                    Good first read
                  </Badge>
                )}
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex items-start gap-8">
        {content && headings.length >= 3 && (
          <nav aria-label="On this page" className="sticky top-32 hidden w-48 shrink-0 pt-2 lg:block">
            <p className="eyebrow mb-3">On this page</p>
            <ul className="flex flex-col gap-2.5 border-l border-border text-[13px]">
              {headings.map((h) => (
                <li key={h.id}>
                  <a href={`#${h.id}`} className="-ml-px block border-l-2 border-transparent pl-3 text-muted-foreground hover:border-iris hover:text-heading">
                    {h.text}
                  </a>
                </li>
              ))}
            </ul>
          </nav>
        )}

        <Card className="min-w-0 flex-1 px-5 py-7 sm:px-12 sm:py-9">
          {content && !isWriting ? (
            <>
              <RichText blocks={blocks} className="max-w-[40rem]" />
              <div className="mt-8 flex flex-col gap-3 border-t border-divider pt-4 sm:flex-row sm:items-center sm:justify-between">
                <span className="flex items-center gap-2 text-xs text-subtle-foreground">
                  <Badge>AI-generated</Badge>
                  Written from this paper&apos;s text. Check key numbers against the paper.
                </span>
                <span className="flex gap-1.5">
                  <Button size="sm" onClick={copy}>
                    {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
                    {copied ? "Copied" : "Copy"}
                  </Button>
                  <Button size="sm" onClick={() => write(tone, true)} disabled={Boolean(writing)}>
                    <RotateCw aria-hidden />
                    Rewrite
                  </Button>
                </span>
              </div>
              {error && <p role="alert" className="mt-3 text-sm text-rose">{error}</p>}
            </>
          ) : isWriting ? (
            <div role="status" aria-live="polite" className="max-w-[40rem]">
              <p className="text-sm text-muted-foreground">Writing the {meta.label} summary. This usually takes 10 to 40 seconds.</p>
              <div className="mt-6 flex flex-col gap-3" aria-hidden>
                <Skeleton className="h-4 w-1/3" />
                <Skeleton className="h-3.5 w-full" />
                <Skeleton className="h-3.5 w-11/12" />
                <Skeleton className="h-3.5 w-4/5" />
                <Skeleton className="mt-4 h-4 w-1/4" />
                <Skeleton className="h-3.5 w-full" />
                <Skeleton className="h-3.5 w-3/4" />
              </div>
            </div>
          ) : (
            <div className="flex max-w-[40rem] flex-col items-start gap-3">
              <h3 className="text-[17px] font-semibold">{meta.label} summary</h3>
              <p className="text-sm leading-relaxed text-muted-foreground">
                {meta.description}. Written by AI from this paper&apos;s text, then saved so it opens instantly next time.
              </p>
              {error && (
                <p role="alert" className="text-sm text-rose">
                  {error}
                </p>
              )}
              <Button variant="primary" className="mt-1" onClick={() => write(tone)} disabled={Boolean(writing)}>
                {error ? "Try again" : "Write this summary"}
              </Button>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}

export default SummaryPanel;
