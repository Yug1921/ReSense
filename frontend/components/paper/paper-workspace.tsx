"use client";

import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
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
import { AiPicker } from "@/components/ai/ai-picker";
import { ThemeToggle } from "@/components/theme/theme-toggle";

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
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const requestedTab = searchParams.get("tab");
  const activeTab: TabId = isTabId(requestedTab) ? requestedTab : "overview";
  const tabRefs = useRef<Partial<Record<TabId, HTMLButtonElement | null>>>({});
  const indicatorRef = useRef<HTMLSpanElement>(null);

  // Slide the underline to the selected tab (and keep it there on resize).
  useLayoutEffect(() => {
    function place() {
      const tab = tabRefs.current[activeTab];
      const indicator = indicatorRef.current;
      if (!tab || !indicator) return;
      indicator.style.width = `${tab.offsetWidth}px`;
      indicator.style.transform = `translateX(${tab.offsetLeft}px)`;
      // No slide on first placement, only on changes after it.
      requestAnimationFrame(() => indicator.setAttribute("data-ready", ""));
    }
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [activeTab]);

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

  // Which way the new panel slides in: from the right when moving to a later tab.
  const [direction, setDirection] = useState<1 | -1>(1);

  function selectTab(id: TabId) {
    if (id === activeTab) return;
    const order = (tab: TabId) => TABS.findIndex((t) => t.id === tab);
    setDirection(order(id) > order(activeTab) ? 1 : -1);
    const params = new URLSearchParams(searchParams.toString());
    if (id === "overview") params.delete("tab");
    else params.set("tab", id);
    const query = params.toString();
    // Update the address without a navigation, so the switch is instant
    // (Next.js keeps useSearchParams in sync with history.replaceState).
    window.history.replaceState(null, "", query ? `${pathname}?${query}` : pathname);
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
                {reading && <p className="truncate text-xs text-subtle-foreground">{reading}</p>}
              </>
            ) : (
              <div className="flex flex-col gap-1.5">
                <span className="sr-only">Loading paper</span>
                <Skeleton className="h-4 w-56" />
                <Skeleton className="h-3 w-36" />
              </div>
            )}
          </div>
          <AiPicker />
          <ThemeToggle />
          <AccountMenu />
        </div>
        <div
          role="tablist"
          aria-label="Paper sections"
          onKeyDown={handleTabKeys}
          // Tab labels line up with the paper title above (back button 32px + 12px gap, minus the tab's own padding).
          className="relative mx-auto flex max-w-6xl gap-1 overflow-x-auto overflow-y-hidden px-4 pl-[calc(1rem+30px)] [scrollbar-width:none] sm:px-10 sm:pl-[calc(2.5rem+30px)] [&::-webkit-scrollbar]:hidden"
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
                  "px-3.5 py-2.5 text-sm transition-colors duration-300",
                  selected ? "text-heading" : "text-muted-foreground hover:text-heading"
                )}
              >
                {tab.label}
              </button>
            );
          })}
          <span
            ref={indicatorRef}
            aria-hidden
            className="pointer-events-none absolute bottom-0 left-0 h-0.5 w-0 rounded-full bg-iris data-[ready]:transition-[transform,width] data-[ready]:duration-[380ms] data-[ready]:ease-[cubic-bezier(0.4,0,0.2,1)]"
          />
        </div>
      </header>

      <main className="mx-auto max-w-6xl overflow-x-clip px-4 py-8 sm:px-10">
        {session ? (
          // Every tab stays mounted (just hidden) so switching back keeps its state.
          TABS.map((tab) => (
            <section
              key={tab.id}
              role="tabpanel"
              id={`panel-${tab.id}`}
              aria-labelledby={`tab-${tab.id}`}
              hidden={tab.id !== activeTab}
              className={direction === 1 ? "animate-panel-in-right" : "animate-panel-in-left"}
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
              {tab.id === "summary" && <SummaryPanel paperId={paperId} initialSummaries={session.summaries} paperName={paper?.filename} />}
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
