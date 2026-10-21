"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { cn } from "@/lib/utils";
import { ApiError, getSession, type SessionResponse } from "@/lib/api";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { OverviewPanel } from "@/components/overview/overview-panel";
import { SummaryPanel } from "@/components/summary/summary-panel";
import { AskPanel } from "@/components/qa/ask-panel";
import { IntegrityPanel } from "@/components/integrity/integrity-panel";
import { AccountMenu } from "@/components/auth/account-menu";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "summary", label: "Summary" },
  { id: "ask", label: "Ask" },
  { id: "integrity", label: "Integrity" },
] as const;

type TabId = (typeof TABS)[number]["id"];

const WORDS_PER_MINUTE = 250;

function isTabId(value: string | null): value is TabId {
  return TABS.some((tab) => tab.id === value);
}

function readingLine(wordCount?: number) {
  if (!wordCount) return null;
  const minutes = Math.max(1, Math.round(wordCount / WORDS_PER_MINUTE));
  return `${wordCount.toLocaleString("en-US")} words · about ${minutes} min read`;
}

type LoadState =
  | { status: "loading" }
  | { status: "ready"; session: SessionResponse }
  | { status: "missing" }
  | { status: "error"; message: string };

export function PaperWorkspace({ paperId }: { paperId: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const requestedTab = searchParams.get("tab");
  const activeTab: TabId = isTabId(requestedTab) ? requestedTab : "overview";
  const tabRefs = useRef<Partial<Record<TabId, HTMLButtonElement | null>>>({});

  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    getSession(paperId)
      .then((session) => {
        if (!cancelled) setLoad({ status: "ready", session });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setLoad({ status: "missing" });
          return;
        }
        setLoad({
          status: "error",
          message:
            err instanceof ApiError && err.status !== 0
              ? err.message
              : "We couldn't reach ReSense. Check your connection and try again.",
        });
      });
    return () => {
      cancelled = true;
    };
  }, [paperId, attempt]);

  function selectTab(id: TabId) {
    const params = new URLSearchParams(searchParams.toString());
    if (id === "overview") params.delete("tab");
    else params.set("tab", id);
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }

  function handleTabKeys(event: KeyboardEvent<HTMLDivElement>) {
    const index = TABS.findIndex((tab) => tab.id === activeTab);
    let next: number;
    if (event.key === "ArrowRight") next = (index + 1) % TABS.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + TABS.length) % TABS.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = TABS.length - 1;
    else return;
    event.preventDefault();
    const id = TABS[next].id;
    selectTab(id);
    tabRefs.current[id]?.focus();
  }

  if (load.status === "missing" || load.status === "error") {
    return (
      <main className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center gap-3 px-6 text-center">
        <h1 className="text-xl font-semibold">
          {load.status === "missing" ? "We couldn't find this paper" : "Something went wrong"}
        </h1>
        <p className="text-sm leading-relaxed text-muted-foreground">
          {load.status === "missing"
            ? "The link may be old, or the paper was removed. Upload it again to keep working."
            : load.message}
        </p>
        <div className="mt-3 flex gap-2">
          {load.status === "error" && (
            <Button
              onClick={() => {
                setLoad({ status: "loading" });
                setAttempt((value) => value + 1);
              }}
            >
              Try again
            </Button>
          )}
          <Link href="/" className={buttonVariants({ variant: "primary" })}>
            Go to home
          </Link>
        </div>
      </main>
    );
  }

  const session = load.status === "ready" ? load.session : null;
  const paper = session?.paper;
  const reading = readingLine(paper?.structure.word_count);

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-40 border-b border-divider bg-background/90 backdrop-blur-md">
        <div className="mx-auto flex h-15 max-w-6xl items-center gap-3 px-4 sm:px-10">
          <Link
            href="/"
            aria-label="Back to home"
            className="inline-flex size-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-raised hover:text-heading"
          >
            <ArrowLeft className="size-[18px]" />
          </Link>
          <div className="min-w-0 flex-1">
            {paper ? (
              <>
                <h1 className="truncate text-[15px] font-medium leading-tight">{paper.filename}</h1>
                {reading && <p className="text-xs text-subtle-foreground">{reading}</p>}
              </>
            ) : (
              <div className="flex flex-col gap-1.5">
                <span className="sr-only">Loading paper</span>
                <Skeleton className="h-4 w-56" />
                <Skeleton className="h-3 w-36" />
              </div>
            )}
          </div>
          <AccountMenu />
        </div>
        <div
          role="tablist"
          aria-label="Paper sections"
          onKeyDown={handleTabKeys}
          className="mx-auto flex max-w-6xl gap-1 overflow-x-auto px-4 sm:px-10"
        >
          {TABS.map((tab) => {
            const selected = tab.id === activeTab;
            return (
              <button
                key={tab.id}
                ref={(node) => {
                  tabRefs.current[tab.id] = node;
                }}
                type="button"
                role="tab"
                id={`tab-${tab.id}`}
                aria-selected={selected}
                aria-controls={`panel-${tab.id}`}
                tabIndex={selected ? 0 : -1}
                onClick={() => selectTab(tab.id)}
                className={cn(
                  "-mb-px border-b-2 px-3.5 py-2.5 text-sm transition-colors",
                  selected
                    ? "border-iris text-heading"
                    : "border-transparent text-muted-foreground hover:text-heading"
                )}
              >
                {tab.label}
              </button>
            );
          })}
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-8 sm:px-10">
        {session ? (
          // Every tab stays mounted (just hidden) so switching back keeps its state.
          TABS.map((tab) => (
            <section
              key={tab.id}
              role="tabpanel"
              id={`panel-${tab.id}`}
              aria-labelledby={`tab-${tab.id}`}
              hidden={tab.id !== activeTab}
            >
              {tab.id === "overview" && (
                <OverviewPanel
                  paperId={paperId}
                  wordCount={paper?.structure.word_count}
                  initialAnalysis={session.analysis}
                  onOpenTab={(id) => {
                    selectTab(id);
                    window.scrollTo({ top: 0 });
                  }}
                />
              )}
              {tab.id === "summary" && <SummaryPanel paperId={paperId} initialSummaries={session.summaries} />}
              {tab.id === "ask" && (
                <AskPanel paperId={paperId} initialHistory={session.chat_history} />
              )}
              {tab.id === "integrity" && <IntegrityPanel paperId={paperId} />}
            </section>
          ))
        ) : (
          <div className="flex flex-col gap-4" aria-busy="true">
            <Skeleton className="h-28 w-full rounded-xl" />
            <Skeleton className="h-64 w-full rounded-xl" />
          </div>
        )}
      </main>
    </div>
  );
}

export default PaperWorkspace;
