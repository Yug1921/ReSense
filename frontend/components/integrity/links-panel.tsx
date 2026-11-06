"use client";

import { useEffect, useState } from "react";
import { ExternalLink, FileLock2, FileCheck2, Loader2, RotateCw } from "lucide-react";
import { checkLinks, getSavedLinkCheck, type LinkCheckResponse, type LinkItem, type LinkStatus } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { checkedLine, errorMessage, FilterChips, LoadError, LoadingBlocks, Num, StartCard } from "@/components/integrity/shared";

type Filter = "review" | "all";

const LINK_STATUS: Record<LinkStatus, { label: string; tone: "sage" | "rose" | "slate"; dot: string }> = {
  broken: { label: "Broken", tone: "rose", dot: "bg-rose" },
  unconfirmed: { label: "Couldn't confirm", tone: "slate", dot: "bg-slate" },
  skipped: { label: "Not opened", tone: "slate", dot: "bg-slate" },
  working: { label: "Works", tone: "sage", dot: "bg-sage" },
};

function failMessage(err: unknown) {
  return errorMessage(err, "We couldn't check this paper's links. Try again.");
}

function shortUrl(url: string) {
  return url.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "");
}

function LinkRow({ link }: { link: LinkItem }) {
  const meta = LINK_STATUS[link.status];
  return (
    <li className="flex flex-col gap-1.5 border-b border-divider px-4 py-3 last:border-b-0 sm:flex-row sm:items-start sm:gap-4">
      <div className="min-w-0 flex-1">
        <a
          href={link.url}
          target="_blank"
          rel="noopener noreferrer nofollow"
          className="inline-flex max-w-full items-center gap-1.5 text-sm text-foreground hover:text-iris"
        >
          <span className="figures truncate">{shortUrl(link.url)}</span>
          <ExternalLink className="size-3.5 shrink-0 text-subtle-foreground" aria-hidden />
          <span className="sr-only">(opens in a new tab)</span>
        </a>
        <p className="mt-0.5 text-xs text-subtle-foreground">
          {link.where === "references" ? "In the reference list" : "In the paper's text"}
          {link.note && <> · {link.note}</>}
          {link.final_url && <> · now at {shortUrl(link.final_url)}</>}
        </p>
      </div>
      <Badge tone={meta.tone} className="self-start">
        {meta.label}
        {link.code && link.status !== "working" ? <span className="figures">{link.code}</span> : null}
      </Badge>
    </li>
  );
}

function Statements({ report }: { report: LinkCheckResponse }) {
  const onRequest = report.statements.filter((s) => s.kind === "on_request");
  const shared = report.statements.filter((s) => s.kind === "public");
  return (
    <section className="mt-6">
      <h3 className="text-[13px] font-medium text-foreground">Data and code</h3>
      {report.statements.length === 0 ? (
        <p className="mt-2.5 rounded-xl border border-border bg-card px-5 py-4 text-sm text-muted-foreground">
          The paper doesn&apos;t say where its data or code can be found. If you need them, you may have to contact the
          authors.
        </p>
      ) : (
        <ul className="mt-2.5 flex flex-col gap-2.5">
          {[...onRequest, ...shared].map((statement) => {
            const request = statement.kind === "on_request";
            return (
              <li
                key={statement.text}
                className={cn(
                  "flex gap-3 rounded-xl border px-4 py-3.5",
                  request ? "border-honey/40 bg-honey/[0.05]" : "border-border bg-card"
                )}
              >
                {request ? (
                  <FileLock2 className="mt-0.5 size-4 shrink-0 text-honey" aria-hidden />
                ) : (
                  <FileCheck2 className="mt-0.5 size-4 shrink-0 text-sage" aria-hidden />
                )}
                <div>
                  <p className={cn("text-[13px] font-medium", request ? "text-honey" : "text-sage")}>
                    {request ? "Only available on request" : "Shared publicly"}
                  </p>
                  <p className="mt-1 text-[13px] leading-relaxed text-foreground">&ldquo;{statement.text}&rdquo;</p>
                  {request && (
                    <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
                      Studies find that most requests for data &ldquo;available on request&rdquo; go unanswered, so
                      these results may be hard to reproduce.
                    </p>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

export function LinksPanel({ paperId }: { paperId: string }) {
  const [load, setLoad] = useState<{ status: "loading" | "ready" } | { status: "error"; message: string }>({
    status: "loading",
  });
  const [attempt, setAttempt] = useState(0);
  const [report, setReport] = useState<LinkCheckResponse | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("review");

  function show(next: LinkCheckResponse | null) {
    setReport(next);
    if (next) setFilter(next.working === next.total ? "all" : "review");
  }

  useEffect(() => {
    let cancelled = false;
    getSavedLinkCheck(paperId)
      .then((saved) => {
        if (cancelled) return;
        show(saved);
        setLoad({ status: "ready" });
      })
      .catch((err: unknown) => !cancelled && setLoad({ status: "error", message: failMessage(err) }));
    return () => {
      cancelled = true;
    };
  }, [paperId, attempt]);

  function run(force: boolean) {
    if (checking) return;
    setError(null);
    setChecking(true);
    checkLinks(paperId, force)
      .then(show)
      .catch((err: unknown) => setError(failMessage(err)))
      .finally(() => setChecking(false));
  }

  if (load.status === "loading") return <LoadingBlocks />;
  if (load.status === "error") {
    return (
      <LoadError
        message={load.message}
        onRetry={() => {
          setLoad({ status: "loading" });
          setAttempt((value) => value + 1);
        }}
      />
    );
  }

  if (!report) {
    return (
      <StartCard
        title="Can these results be reproduced?"
        action="Check links and data"
        busyAction="Checking links…"
        timing="Usually under a minute."
        busyTiming="Opening each link in the paper."
        checking={checking}
        error={error}
        onStart={() => run(false)}
      >
        ReSense opens every web link in the paper to see if it still works, and finds what the paper says about its data
        and code: shared publicly, or only &ldquo;available on request&rdquo;.
      </StartCard>
    );
  }

  const review = report.links.filter((link) => link.status !== "working");
  const visible = filter === "review" ? review : report.links;
  const checked = checkedLine(report.checked_at);

  return (
    <div>
      <section className="rounded-xl border border-border bg-card px-5 py-5 sm:px-7 sm:py-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
          <div>
            <p className="eyebrow">Links and data</p>
            <p className="mt-2 max-w-3xl text-lg leading-snug text-heading sm:text-xl">
              {report.total === 0 ? (
                "This paper has no web links to check."
              ) : (
                <>
                  <Num>{report.working}</Num> of <Num>{report.total}</Num> links work.
                  {report.broken > 0 && (
                    <span className="text-foreground">
                      {" "}
                      <Num>{report.broken}</Num> {report.broken === 1 ? "is" : "are"} broken
                      {report.unconfirmed > 0 ? "," : "."}
                    </span>
                  )}
                  {report.unconfirmed > 0 && (
                    <span className="text-foreground">
                      {" "}
                      {report.broken > 0 ? "and " : ""}
                      <Num>{report.unconfirmed}</Num> couldn&apos;t be confirmed.
                    </span>
                  )}
                </>
              )}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-3 sm:flex-col sm:items-end sm:gap-1.5">
            <Button size="sm" onClick={() => run(true)} disabled={checking}>
              {checking ? <Loader2 className="animate-spin" aria-hidden /> : <RotateCw aria-hidden />}
              {checking ? "Checking…" : "Check again"}
            </Button>
            {checked && !checking && <span className="text-xs text-subtle-foreground">{checked}</span>}
          </div>
        </div>
        {error && (
          <p role="alert" className="mt-4 text-sm text-rose">
            {error}
          </p>
        )}
        <p className="mt-4 border-t border-divider pt-3.5 text-xs leading-relaxed text-subtle-foreground">
          &ldquo;Couldn&apos;t confirm&rdquo; means the site blocks automatic checks or didn&apos;t answer in time. Open
          those links yourself to be sure.
        </p>
      </section>

      <Statements report={report} />

      {report.total > 0 && (
        <section className={cn("mt-2 transition-opacity", checking && "opacity-60")}>
          <FilterChips
            label="Show links"
            value={filter}
            onChange={setFilter}
            options={[
              { id: "review", label: "To review", count: review.length },
              { id: "all", label: "All", count: report.total },
            ]}
          />
          {visible.length === 0 ? (
            <p className="mt-4 rounded-xl border border-border bg-card px-5 py-6 text-sm text-muted-foreground">
              Nothing to review. Every link opened.
            </p>
          ) : (
            <ul className="mt-4 overflow-hidden rounded-xl border border-border bg-card">
              {visible.map((link) => (
                <LinkRow key={link.url} link={link} />
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}
