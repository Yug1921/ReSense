"use client";

import { useEffect, useId, useState } from "react";
import { Loader2, RotateCw } from "lucide-react";
import {
  ApiError,
  checkClaims,
  getSavedClaimCheck,
  type ClaimCheckResponse,
  type ClaimItem,
  type ClaimVerdict,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { checkedLine, errorMessage, FilterChips, LoadError, LoadingBlocks, Num, StartCard } from "@/components/integrity/shared";

type Filter = "review" | "cannot_tell" | "all";

const NEEDS_REVIEW: ClaimVerdict[] = ["not_supported", "partial", "unchecked"];

const VERDICT: Record<ClaimVerdict, { label: string; tone: "sage" | "honey" | "rose" | "slate"; dot: string; meaning: string }> = {
  not_supported: {
    label: "Doesn't match",
    tone: "rose",
    dot: "bg-rose",
    meaning: "The cited paper's abstract is about something else, or says something different. Read the source to check.",
  },
  partial: {
    label: "Partly supported",
    tone: "honey",
    dot: "bg-honey",
    meaning: "The abstract backs part of the claim, or says it in weaker or different terms.",
  },
  cannot_tell: {
    label: "Abstract doesn't say",
    tone: "slate",
    dot: "bg-slate",
    meaning: "The claim is about a detail an abstract wouldn't mention, so it can only be checked in the full paper.",
  },
  unchecked: {
    label: "Not checked",
    tone: "slate",
    dot: "bg-slate",
    meaning: "The AI didn't answer for this one. Check again to finish it.",
  },
  supported: {
    label: "Supported",
    tone: "sage",
    dot: "bg-sage",
    meaning: "The cited paper's abstract backs what the sentence says about it.",
  },
};

const ORDER: ClaimVerdict[] = ["supported", "partial", "not_supported", "cannot_tell", "unchecked"];

function failMessage(err: unknown) {
  if (err instanceof ApiError && err.status === 503) return err.message;
  return errorMessage(err, "We couldn't check this paper's claims. Try again.");
}

/** One quoted sentence and the check against each source it cites (a sentence citing [10, 41] is checked twice). */
function ClaimRow({ checks }: { checks: ClaimItem[] }) {
  return (
    <li className="border-b border-divider px-4 py-3.5 last:border-b-0">
      <p className="text-sm leading-relaxed text-foreground">&ldquo;{checks[0].sentence}&rdquo;</p>
      {checks.map((claim) => {
        const meta = VERDICT[claim.verdict];
        return (
          <div key={claim.ref} className="mt-2.5 flex flex-col gap-1.5 sm:flex-row sm:items-start sm:gap-4">
            <div className="min-w-0 flex-1">
              <p className="text-xs leading-relaxed text-subtle-foreground">
                Cites <span className="figures">[{claim.ref}]</span>{" "}
                <span className="text-muted-foreground">{claim.source_title ?? claim.cited_title}</span>
                {claim.abstract_source && <> · abstract from {claim.abstract_source}</>}
              </p>
              {claim.reason && <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground">{claim.reason}</p>}
            </div>
            <Badge tone={meta.tone} className="self-start">
              {meta.label}
            </Badge>
          </div>
        );
      })}
    </li>
  );
}

function bySentence(claims: ClaimItem[]) {
  const groups = new Map<string, ClaimItem[]>();
  for (const claim of claims) groups.set(claim.sentence, [...(groups.get(claim.sentence) ?? []), claim]);
  return [...groups.values()];
}

export function ClaimsPanel({ paperId, onOpenReferences }: { paperId: string; onOpenReferences: () => void }) {
  const [load, setLoad] = useState<{ status: "loading" | "ready" } | { status: "error"; message: string }>({
    status: "loading",
  });
  const [attempt, setAttempt] = useState(0);
  const [report, setReport] = useState<ClaimCheckResponse | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needsReferences, setNeedsReferences] = useState(false);
  const [filter, setFilter] = useState<Filter>("review");
  const [showMeaning, setShowMeaning] = useState(false);
  const meaningId = useId();

  function show(next: ClaimCheckResponse | null) {
    setReport(next);
    if (next) setFilter(next.claims.some((claim) => NEEDS_REVIEW.includes(claim.verdict)) ? "review" : "all");
  }

  useEffect(() => {
    let cancelled = false;
    getSavedClaimCheck(paperId)
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
    setNeedsReferences(false);
    setChecking(true);
    checkClaims(paperId, force)
      .then(show)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 409) setNeedsReferences(true);
        setError(failMessage(err));
      })
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
        title="Do the cited papers say what this paper claims?"
        action="Check claims"
        busyAction="Checking claims…"
        timing="Takes a minute or two. Run the reference check first."
        busyTiming="Reading each cited paper's abstract and comparing it with the claim."
        checking={checking}
        error={needsReferences ? null : error}
        onStart={() => run(false)}
      >
        <p>
          ReSense finds sentences that cite a source, fetches that source&apos;s abstract, and asks the AI whether the
          abstract supports what the sentence says. It checks up to 30 of the clearest claims.
        </p>
        {needsReferences && (
          <p role="alert" className="mt-3 text-sm text-honey">
            The claim check uses the reference check&apos;s results.{" "}
            <button type="button" onClick={onOpenReferences} className="text-iris underline-offset-2 hover:underline">
              Check the references first
            </button>
            .
          </p>
        )}
      </StartCard>
    );
  }

  const counts: Record<ClaimVerdict, number> = {
    supported: report.supported,
    partial: report.partial,
    not_supported: report.not_supported,
    cannot_tell: report.cannot_tell,
    unchecked: report.unchecked,
  };
  const review = report.claims.filter((claim) => NEEDS_REVIEW.includes(claim.verdict));
  const cannotTell = report.claims.filter((claim) => claim.verdict === "cannot_tell");
  const visible = filter === "review" ? review : filter === "cannot_tell" ? cannotTell : report.claims;
  const checked = checkedLine(report.checked_at);
  const barLabel = ORDER.map((v) => `${counts[v]} ${VERDICT[v].label.toLowerCase()}`).join(", ");

  return (
    <div>
      <section className="rounded-xl border border-border bg-card px-5 py-5 sm:px-7 sm:py-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
          <div>
            <p className="eyebrow">Citation claims</p>
            <p className="mt-2 max-w-3xl text-lg leading-snug text-heading sm:text-xl">
              {report.total === 0 ? (
                "We didn't find claims we could check against a cited paper's abstract."
              ) : (
                <>
                  <Num>{report.supported}</Num> of <Num>{report.total}</Num> checked claims are backed by the cited
                  paper&apos;s abstract.
                  {report.not_supported > 0 && (
                    <span className="text-foreground">
                      {" "}
                      <Num>{report.not_supported}</Num> {report.not_supported === 1 ? "doesn't" : "don't"} match what
                      the source says.
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

        {report.total > 0 && (
          <>
            <div role="img" aria-label={barLabel} className="mt-5 flex h-2 gap-0.5 overflow-hidden rounded-full">
              {ORDER.map(
                (verdict) =>
                  counts[verdict] > 0 && (
                    <div key={verdict} className={VERDICT[verdict].dot} style={{ flexGrow: counts[verdict] }} />
                  )
              )}
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-2 text-[13px] text-muted-foreground">
              {ORDER.filter((verdict) => verdict !== "unchecked" || counts.unchecked > 0).map((verdict) => (
                <span key={verdict} className="inline-flex items-center gap-2">
                  <span aria-hidden className={cn("size-2 rounded-full", VERDICT[verdict].dot)} />
                  {VERDICT[verdict].label}
                  <span className="figures text-foreground">{counts[verdict]}</span>
                </span>
              ))}
              <button
                type="button"
                aria-expanded={showMeaning}
                aria-controls={meaningId}
                onClick={() => setShowMeaning((value) => !value)}
                className="text-iris transition-colors hover:text-iris-strong sm:ml-auto"
              >
                {showMeaning ? "Hide explanations" : "What do these mean?"}
              </button>
            </div>
            <dl id={meaningId} hidden={!showMeaning} className="mt-4 grid gap-3 sm:grid-cols-2">
              {ORDER.filter((verdict) => verdict !== "unchecked").map((verdict) => (
                <div key={verdict} className="rounded-lg border border-divider bg-background px-3.5 py-3">
                  <dt className="flex items-center gap-2 text-[13px] font-medium text-heading">
                    <span aria-hidden className={cn("size-2 rounded-full", VERDICT[verdict].dot)} />
                    {VERDICT[verdict].label}
                  </dt>
                  <dd className="mt-1 text-[13px] leading-relaxed text-muted-foreground">{VERDICT[verdict].meaning}</dd>
                </div>
              ))}
            </dl>
          </>
        )}

        {error && (
          <p role="alert" className="mt-4 text-sm text-rose">
            {error}
          </p>
        )}
        <p className="mt-4 border-t border-divider pt-3.5 text-xs leading-relaxed text-subtle-foreground">
          Found <span className="figures">{report.citing_sentences}</span> sentences that cite a source and checked the
          clearest ones against the cited paper&apos;s abstract
          {report.without_abstract > 0 && (
            <>
              {" "}
              (<span className="figures">{report.without_abstract}</span> cited works had no abstract we could read)
            </>
          )}
          . The AI judges from the abstract alone, so &ldquo;Doesn&apos;t match&rdquo; is a reason to read the source,
          not proof of an error.
        </p>
      </section>

      {report.total > 0 && (
        <section className={cn("transition-opacity", checking && "opacity-60")}>
          <FilterChips
            label="Show claims"
            value={filter}
            onChange={setFilter}
            options={[
              { id: "review", label: "To review", count: review.length },
              ...(cannotTell.length > 0
                ? [{ id: "cannot_tell" as const, label: "Abstract doesn't say", count: cannotTell.length }]
                : []),
              { id: "all", label: "All", count: report.total },
            ]}
          />
          {visible.length === 0 ? (
            <p className="mt-4 rounded-xl border border-border bg-card px-5 py-6 text-sm text-muted-foreground">
              {filter === "review"
                ? "Nothing to review. No checked claim conflicts with its source."
                : "No claims in this group."}
            </p>
          ) : (
            <ul className="mt-4 overflow-hidden rounded-xl border border-border bg-card">
              {bySentence(visible).map((checks) => (
                <ClaimRow key={checks[0].sentence} checks={checks} />
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}
