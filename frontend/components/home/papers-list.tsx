"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { FileText, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { ApiError, deletePaper, listPapers, type PaperListItem } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

const DAY = 24 * 60 * 60 * 1000;

function openedLabel(iso: string) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const startOfToday = new Date();
  startOfToday.setHours(0, 0, 0, 0);
  const diff = startOfToday.getTime() - date.getTime();
  if (diff <= 0) return "Added today";
  if (diff <= DAY) return "Added yesterday";
  const sameYear = date.getFullYear() === startOfToday.getFullYear();
  return `Added ${date.toLocaleDateString("en-US", { month: "short", day: "numeric", ...(sameYear ? {} : { year: "numeric" }) })}`;
}

export function PapersList() {
  const [papers, setPapers] = useState<PaperListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);

  useEffect(() => {
    listPapers()
      .then(setPapers)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 401) return;
        setError("We couldn't load your papers. Refresh the page to try again.");
      });
  }, []);

  async function remove(paper: PaperListItem) {
    setRemoving(paper.paper_id);
    try {
      await deletePaper(paper.paper_id);
      setPapers((current) => current?.filter((p) => p.paper_id !== paper.paper_id) ?? null);
      toast.success(`Removed ${paper.filename}`);
    } catch {
      toast.error("We couldn't remove that paper. Try again.");
    } finally {
      setRemoving(null);
      setConfirming(null);
    }
  }

  return (
    <section aria-labelledby="your-papers" className="w-full">
      <h2 id="your-papers" className="mb-2.5 text-[13px] font-medium text-muted-foreground">
        Your papers
      </h2>
      {error ? (
        <p className="text-sm text-muted-foreground">{error}</p>
      ) : papers === null ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-[52px] w-full rounded-lg" />
          <Skeleton className="h-[52px] w-full rounded-lg" />
        </div>
      ) : papers.length === 0 ? (
        <p className="rounded-xl border border-dashed border-border px-4 py-6 text-center text-sm text-subtle-foreground">
          Papers you upload will appear here.
        </p>
      ) : (
        <ul className="overflow-hidden rounded-xl border border-border bg-card">
          {papers.map((paper) => {
            const readable = paper.status === "ready";
            const meta = [
              paper.word_count ? `${paper.word_count.toLocaleString("en-US")} words` : null,
              openedLabel(paper.uploaded_at),
            ]
              .filter(Boolean)
              .join(" · ");
            return (
              <li key={paper.paper_id} className="group flex items-center gap-3 border-b border-divider px-4 py-3 last:border-b-0">
                <FileText className="size-4 shrink-0 text-subtle-foreground" aria-hidden />
                <div className="min-w-0 flex-1">
                  {readable ? (
                    <Link
                      href={`/paper/${paper.paper_id}`}
                      className="block truncate text-sm text-foreground hover:text-heading"
                    >
                      {paper.filename}
                    </Link>
                  ) : (
                    <span className="block truncate text-sm text-muted-foreground">{paper.filename}</span>
                  )}
                  <p className="text-xs text-subtle-foreground">{meta}</p>
                </div>
                {!readable && <Badge tone="rose">Couldn&apos;t read text</Badge>}
                {confirming === paper.paper_id ? (
                  <span className="flex items-center gap-1.5">
                    <span className="hidden text-xs text-muted-foreground sm:inline">Remove with its summaries?</span>
                    <Button size="sm" variant="ghost" onClick={() => setConfirming(null)} disabled={removing === paper.paper_id}>
                      Cancel
                    </Button>
                    <Button
                      size="sm"
                      className="border-rose/40 text-rose hover:border-rose hover:bg-rose/10"
                      onClick={() => remove(paper)}
                      disabled={removing === paper.paper_id}
                    >
                      Remove
                    </Button>
                  </span>
                ) : (
                  <Button
                    size="icon"
                    variant="ghost"
                    aria-label={`Remove ${paper.filename}`}
                    onClick={() => setConfirming(paper.paper_id)}
                    className="opacity-100 sm:opacity-0 sm:group-focus-within:opacity-100 sm:group-hover:opacity-100"
                  >
                    <Trash2 aria-hidden />
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
