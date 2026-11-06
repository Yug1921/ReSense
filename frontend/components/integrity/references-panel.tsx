"use client";

import { useEffect, useId, useState, type ReactNode } from "react";
import { ChevronDown, ExternalLink, Loader2, OctagonAlert, RotateCw, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  checkReferences,
  getSavedReferenceCheck,
  type ReferenceCheckResponse,
  type ReferenceItem,
  type ReferenceNotice,
  type ReferenceStatus,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { checkedLine, errorMessage as baseErrorMessage, FilterChips, LoadError, Num, StartCard } from "@/components/integrity/shared";

type Tone = "sage" | "honey" | "rose" | "slate";
type Filter = "review" | "matched" | "all";

const STATUS: Record<ReferenceStatus, { label: string; tone: Tone; dot: string; bar: string; group: string; meaning: string }> = {
  verified: {
    label: "Matched",
    tone: "sage",
    dot: "bg-sage",
    bar: "bg-sage",
    group: "a published record agrees with the citation",
    meaning: "We found a published record whose title, authors and year agree with the citation.",
  },
  uncertain: {
    label: "Needs a look",
    tone: "honey",
    dot: "bg-honey",
    bar: "bg-honey",
    group: "a record was found, but some details differ from the citation",
    meaning:
      "We found the work, but a detail differs, such as the year or the version (a preprint instead of the conference paper). Usually fine, worth a quick look.",
  },
  not_found: {
    label: "Not found",
    tone: "rose",
    dot: "bg-rose",
    bar: "bg-rose",
    group: "theses, software and reports are often missing from these databases",
    meaning:
      "No record with this title in the databases we search. Many real works (theses, software, reports) aren't listed there, so this is a prompt to check, not proof it was made up.",
  },
  unavailable: {
    label: "Couldn't check",
    tone: "slate",
    dot: "bg-slate",
    bar: "bg-slate",
    group: "a database was busy or down, so these aren't settled yet",
    meaning: "A database was busy or down when we looked. Check again later to settle these.",
  },
};

// Problems first, then everything that matched.
const GROUP_ORDER: ReferenceStatus[] = ["uncertain", "not_found", "unavailable", "verified"];

const SOURCE_LABELS: Record<string, string> = {
  crossref: "Crossref",
  openalex: "OpenAlex",
  arxiv: "arXiv",
  jmlr: "JMLR",
  neurips: "NeurIPS proceedings",
};

function stripNumber(raw: string) {
  return raw.replace(/^\s*(?:\[\d+\]|\(\d+\)|\d+[.)])\s*/, "").replace(/\s+([,.])/g, "$1").trim();
}

function citedYear(raw: string): number | null {
  const years = raw.match(/\b(?:19|20)\d{2}\b/g);
  return years ? Number(years[years.length - 1]) : null;
}

// "A, B, C, D, and E" -> "A, B, C, et al." so a row stays one line.
function shortAuthors(authors: string | null) {
  if (!authors) return null;
  const names = authors
    .split(/\s*,\s*(?:and\s+)?|\s+and\s+/)
    .map((name) => name.trim())
    .filter((name) => name && !/^et\.? al\.?$/i.test(name));
  return names.length > 3 ? `${names.slice(0, 3).join(", ")}, et al.` : authors;
}

function citeLine(item: ReferenceItem) {
  const year = citedYear(item.raw);
  const venue = [item.cited_venue, year].filter(Boolean).join(" ");
  return [shortAuthors(item.cited_authors), venue].filter(Boolean).join(" · ");
}

function isPreprint(item: ReferenceItem) {
  return item.source === "arxiv" || Boolean(item.matched_doi?.toLowerCase().includes("arxiv"));
}

function scholarLink(item: ReferenceItem) {
  const query = item.cited_title ?? stripNumber(item.raw);
  return `https://scholar.google.com/scholar?q=${encodeURIComponent(query)}`;
}

/** A short chip for the row, and a plain sentence for when it is opened. */
function explain(item: ReferenceItem): { chip: string | null; text: string } {
  const cited = citedYear(item.raw);
  const found = item.matched_year;

  if (item.status === "verified") {
    return { chip: null, text: "A published record matches this citation. Open the link to see it." };
  }

  if (item.status === "unavailable") {
    return {
      chip: "Database busy",
      text: "A database was busy or down when we checked, so this one isn't settled yet. Use Check again to retry.",
    };
  }

  if (item.status === "not_found") {
    const raw = item.raw.toLowerCase();
    let chip = "No record found";
    let note = "";
    if (/thesis|dissertation/.test(raw)) {
      chip = "Thesis, not indexed";
      note = "Theses are often not listed there. ";
    } else if (/software|library|toolbox|toolkit|github\.com/.test(raw)) {
      chip = "Software, no exact record";
      note = "Software is often cited by name and rarely has a matching record. ";
    } else if (/tech(?:nical)?\.? report|white ?paper/.test(raw)) {
      chip = "Report, not indexed";
      note = "Reports are often not listed there. ";
    } else if (/https?:\/\/|www\./.test(raw)) {
      chip = "Web page";
      note = "Web pages aren't listed there. ";
    }
    return {
      chip,
      text: `We couldn't find a record with this title in the databases we search. ${note}This isn't proof that it was made up. Search the web to confirm it exists.`,
    };
  }

  // Needs a look.
  if (item.publication_relation === "same_work_version") {
    const version = isPreprint(item) ? "the arXiv preprint" : "a different version";
    const earlier = found && cited && found < cited;
    return {
      chip: earlier ? "Found as an earlier version" : "Found as another version",
      text: `We found this work as ${version}${found ? ` from ${found}` : ""}${
        cited ? `, while the paper cites the ${[item.cited_venue, cited].filter(Boolean).join(" ")} version` : ""
      }. This is usually the same work. Open the link to confirm.`,
    };
  }
  if (item.conflict_fields.includes("first_author")) {
    return {
      chip: "First author differs",
      text: "The title matches, but the record lists a different first author. Open the link to check it is the work the paper means.",
    };
  }
  if (found && cited && found !== cited) {
    const why =
      Math.abs(found - cited) <= 1
        ? "Online and print dates often differ by a year, so this is usually fine."
        : "A re-uploaded copy or a later edition can cause this.";
    return {
      chip: `Record says ${found}`,
      text: `The title matches, but the record we found is dated ${found} while the paper cites ${cited}. ${why} Open the link to confirm.`,
    };
  }
  if (item.match_reason?.includes("incomplete author")) {
    return {
      chip: "Record lists no authors",
      text: "The title matches, but the record we found doesn't list its authors, so we couldn't confirm them.",
    };
  }
  return {
    chip: "Details partly differ",
    text: "The title matches, but the authors, year or type of publication only partly agree with the citation. Open the link to compare.",
  };
}

function errorMessage(err: unknown) {
  return baseErrorMessage(err, "We couldn't check this paper's references. Try again.");
}

const SERIOUS = new Set(["retraction", "withdrawal", "removal", "expression_of_concern"]);

function isSerious(notices: ReferenceNotice[] | undefined) {
  return Boolean(notices?.some((notice) => SERIOUS.has(notice.type)));
}

function noticeChip(notices: ReferenceNotice[] | undefined): string | null {
  const first = notices?.[0];
  if (!first) return null;
  if (first.type === "retraction") return "Retracted";
  if (first.type === "withdrawal" || first.type === "removal") return "Withdrawn";
  if (first.type === "expression_of_concern") return "Expression of concern";
  return "Corrected";
}

function noticeDate(date: string | null) {
  if (!date) return null;
  const parsed = new Date(`${date.length === 4 ? `${date}-01-01` : date}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return date;
  return date.length === 4
    ? date
    : parsed.toLocaleDateString("en-US", { month: "short", day: date.length > 7 ? "numeric" : undefined, year: "numeric" });
}

function Notices({ notices }: { notices: ReferenceNotice[] }) {
  const serious = isSerious(notices);
  return (
    <div
      className={cn(
        "mt-3 rounded-lg border px-3.5 py-3",
        serious ? "border-rose/40 bg-rose/[0.06]" : "border-honey/40 bg-honey/[0.06]"
      )}
    >
      <p className={cn("text-[13px] font-medium", serious ? "text-rose" : "text-honey")}>
        {serious
          ? "This cited work has an editorial notice. Results that rest on it may not hold."
          : "This cited work was later corrected. The correction may change details the paper relies on."}
      </p>
      <ul className="mt-1.5 flex flex-col gap-1 text-[13px] text-muted-foreground">
        {notices.map((notice) => (
          <li key={`${notice.type}-${notice.date}-${notice.notice_doi}`}>
            {notice.label}
            {notice.date && <> · {noticeDate(notice.date)}</>}
            {notice.source && <> · via {notice.source}</>}
            {notice.notice_doi && (
              <>
                {" · "}
                <a
                  href={`https://doi.org/${notice.notice_doi}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-iris hover:text-iris-strong"
                >
                  Read the notice
                  <ExternalLink className="size-3 shrink-0" aria-hidden />
                  <span className="sr-only">(opens in a new tab)</span>
                </a>
              </>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function joinParts(parts: ReactNode[]) {
  return parts.map((part, i) => (
    <span key={i}>
      {i > 0 && (i === parts.length - 1 ? ", and " : ", ")}
      {part}
    </span>
  ));
}

function Lead({ report }: { report: ReferenceCheckResponse }) {
  const { total, verified, uncertain, not_found, unavailable } = report;
  const rest: ReactNode[] = [];
  if (uncertain) rest.push(<><Num>{uncertain}</Num> {uncertain === 1 ? "needs" : "need"} a quick look</>);
  if (not_found)
    rest.push(<><Num>{not_found}</Num> {not_found === 1 ? "was" : "were"} not found in the databases we search</>);
  if (unavailable) rest.push(<><Num>{unavailable}</Num> couldn&apos;t be checked right now</>);
  return (
    <p className="mt-2 max-w-3xl text-lg leading-snug text-heading sm:text-xl">
      {verified === total ? (
        <>
          All <Num>{total}</Num> references matched a published record.
        </>
      ) : (
        <>
          <Num>{verified}</Num> of <Num>{total}</Num> references matched a published record.
        </>
      )}
      {rest.length > 0 && <span className="text-foreground"> {joinParts(rest)}.</span>}
    </p>
  );
}

function ReferenceRow({ item }: { item: ReferenceItem }) {
  const [open, setOpen] = useState(false);
  const detailsId = useId();
  const { chip, text } = explain(item);
  const meta = STATUS[item.status];
  const line = citeLine(item);
  const showRecord = item.matched_title && (item.status === "verified" || item.status === "uncertain");
  const source = item.source ? SOURCE_LABELS[item.source] ?? item.source : null;
  const notices = item.notices ?? [];
  const alert = noticeChip(notices);
  const chipBadge =
    alert || chip ? (
      <span className="flex flex-wrap gap-1.5">
        {alert && (
          <Badge tone={isSerious(notices) ? "rose" : "honey"}>
            <OctagonAlert className="size-3" aria-hidden />
            {alert}
          </Badge>
        )}
        {chip && <Badge tone={meta.tone}>{chip}</Badge>}
      </span>
    ) : null;

  return (
    <li className={cn("border-b border-divider last:border-b-0", open && "bg-raised/40")}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={detailsId}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-start gap-3 px-4 py-3.5 text-left transition-colors hover:bg-raised/60 sm:items-center sm:gap-3.5"
      >
        <span className="figures w-9 shrink-0 pt-0.5 text-xs text-subtle-foreground sm:pt-0">[{item.index}]</span>
        <span className="min-w-0 flex-1">
          <span className={cn("block text-sm", open ? "text-heading" : "text-foreground")}>
            {item.cited_title ?? stripNumber(item.raw)}
          </span>
          {item.cited_title && line && (
            <span className="mt-0.5 block truncate text-xs text-subtle-foreground">{line}</span>
          )}
          {chipBadge && <span className="mt-2 flex sm:hidden">{chipBadge}</span>}
        </span>
        {chipBadge && <span className="hidden sm:flex">{chipBadge}</span>}
        <ChevronDown
          aria-hidden
          className={cn("mt-0.5 size-4 shrink-0 text-subtle-foreground transition-transform sm:mt-0", open && "rotate-180")}
        />
      </button>

      <div id={detailsId} hidden={!open} className="px-4 pb-4 sm:pl-[66px]">
        <div className={cn("grid gap-3", showRecord && "sm:grid-cols-2")}>
          <div className="rounded-lg border border-divider bg-background px-3.5 py-3">
            <p className="eyebrow">In the paper</p>
            <p className="mt-1.5 text-[13px] leading-relaxed text-foreground">{stripNumber(item.raw)}</p>
          </div>
          {showRecord && (
            <div className="rounded-lg border border-divider bg-background px-3.5 py-3">
              <p className="eyebrow">{item.status === "verified" ? "Record we found" : "Closest record we found"}</p>
              <p className="mt-1.5 text-[13px] leading-relaxed text-foreground">
                {item.matched_title}
                {(isPreprint(item) || item.matched_year) && (
                  <span className="text-muted-foreground">
                    {" · "}
                    {[isPreprint(item) && "arXiv preprint", item.matched_year].filter(Boolean).join(", ")}
                  </span>
                )}
              </p>
              {(source || item.matched_doi) && (
                <p className="mt-1.5 text-xs text-subtle-foreground">
                  {source && `via ${source}`}
                  {source && item.matched_doi && " · "}
                  {item.matched_doi && (
                    <a
                      href={`https://doi.org/${item.matched_doi}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="figures inline-flex items-center gap-1 break-all text-iris hover:text-iris-strong"
                    >
                      {item.matched_doi}
                      <ExternalLink className="size-3 shrink-0" aria-hidden />
                      <span className="sr-only">(opens in a new tab)</span>
                    </a>
                  )}
                </p>
              )}
            </div>
          )}
        </div>
        {notices.length > 0 && <Notices notices={notices} />}
        <p className="mt-3 text-[13px] leading-relaxed text-muted-foreground">{text}</p>
        {(item.status === "not_found" || (item.status !== "verified" && !item.matched_doi)) && (
          <a
            href={scholarLink(item)}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-2 inline-flex items-center gap-1.5 text-[13px] text-iris hover:text-iris-strong"
          >
            <Search className="size-3.5" aria-hidden />
            Search the web
            <span className="sr-only">(opens Google Scholar in a new tab)</span>
          </a>
        )}
      </div>
    </li>
  );
}

function Group({ status, items }: { status: ReferenceStatus; items: ReferenceItem[] }) {
  const meta = STATUS[status];
  const headingId = useId();
  if (items.length === 0) return null;
  return (
    <section aria-labelledby={headingId} className="mt-6 first:mt-0">
      <h3 id={headingId} className="flex flex-wrap items-center gap-x-2 text-[13px] font-medium text-foreground">
        <span aria-hidden className={cn("size-2 rounded-full", meta.dot)} />
        {meta.label}
        <span className="figures font-normal text-subtle-foreground">{items.length}</span>
        <span className="hidden font-normal text-subtle-foreground sm:inline">· {meta.group}</span>
      </h3>
      <ul className="mt-2.5 overflow-hidden rounded-xl border border-border bg-card">
        {items.map((item) => (
          <ReferenceRow key={item.index} item={item} />
        ))}
      </ul>
    </section>
  );
}

function RetractionAlert({ report }: { report: ReferenceCheckResponse }) {
  const flagged = report.items.filter((item) => (item.notices ?? []).length > 0);
  const retracted = report.retracted ?? 0;
  const corrected = report.corrected ?? 0;
  if (!report.notices_checked && flagged.length === 0) return null;
  if (flagged.length === 0) {
    return (
      <p className="mt-4 flex items-center gap-2 text-[13px] text-muted-foreground">
        <span aria-hidden className="size-2 rounded-full bg-sage" />
        Retraction alert: none of the matched references has been retracted or corrected.
      </p>
    );
  }
  return (
    <div
      role="alert"
      className={cn(
        "mt-5 rounded-lg border px-4 py-3.5",
        retracted ? "border-rose/40 bg-rose/[0.06]" : "border-honey/40 bg-honey/[0.06]"
      )}
    >
      <p className={cn("flex items-center gap-2 text-sm font-medium", retracted ? "text-rose" : "text-honey")}>
        <OctagonAlert className="size-4 shrink-0" aria-hidden />
        {retracted > 0 && (
          <>
            <Num>{retracted}</Num> cited {retracted === 1 ? "work has" : "works have"} been retracted or flagged
          </>
        )}
        {retracted > 0 && corrected > 0 && ", and "}
        {corrected > 0 && (
          <>
            <Num>{corrected}</Num> {retracted ? "" : "cited "}
            {corrected === 1 ? "was" : "were"} later corrected
          </>
        )}
      </p>
      <ul className="mt-2 flex flex-col gap-1 text-[13px] text-foreground">
        {flagged.map((item) => (
          <li key={item.index} className="flex gap-2">
            <span className="figures shrink-0 text-subtle-foreground">[{item.index}]</span>
            <span>
              {item.cited_title ?? item.matched_title ?? stripNumber(item.raw)}
              <span className="text-muted-foreground"> · {noticeChip(item.notices)}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Summary({
  report,
  checking,
  error,
  onCheckAgain,
}: {
  report: ReferenceCheckResponse;
  checking: boolean;
  error: string | null;
  onCheckAgain: () => void;
}) {
  const [showMeaning, setShowMeaning] = useState(false);
  const meaningId = useId();
  const checked = checkedLine(report.checked_at);
  const counts: Record<ReferenceStatus, number> = {
    verified: report.verified,
    uncertain: report.uncertain,
    not_found: report.not_found,
    unavailable: report.unavailable,
  };
  const barOrder: ReferenceStatus[] = ["verified", "uncertain", "not_found", "unavailable"];
  const barLabel = barOrder.map((status) => `${counts[status]} ${STATUS[status].label.toLowerCase()}`).join(", ");

  return (
    <section className="rounded-xl border border-border bg-card px-5 py-5 sm:px-7 sm:py-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
        <div>
          <p className="eyebrow">Reference check</p>
          <Lead report={report} />
        </div>
        <div className="flex shrink-0 items-center gap-3 sm:flex-col sm:items-end sm:gap-1.5">
          <Button size="sm" onClick={onCheckAgain} disabled={checking}>
            {checking ? <Loader2 className="animate-spin" aria-hidden /> : <RotateCw aria-hidden />}
            {checking ? "Checking…" : "Check again"}
          </Button>
          {checked && !checking && <span className="text-xs text-subtle-foreground">{checked}</span>}
        </div>
      </div>

      <div role="img" aria-label={barLabel} className="mt-5 flex h-2 gap-0.5 overflow-hidden rounded-full">
        {barOrder.map(
          (status) =>
            counts[status] > 0 && (
              <div key={status} className={STATUS[status].bar} style={{ flexGrow: counts[status] }} />
            )
        )}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-2 text-[13px] text-muted-foreground">
        {barOrder.map((status) => (
          <span key={status} className="inline-flex items-center gap-2">
            <span aria-hidden className={cn("size-2 rounded-full", STATUS[status].dot)} />
            {STATUS[status].label}
            <span className="figures text-foreground">{counts[status]}</span>
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
        {barOrder.map((status) => (
          <div key={status} className="rounded-lg border border-divider bg-background px-3.5 py-3">
            <dt className="flex items-center gap-2 text-[13px] font-medium text-heading">
              <span aria-hidden className={cn("size-2 rounded-full", STATUS[status].dot)} />
              {STATUS[status].label}
            </dt>
            <dd className="mt-1 text-[13px] leading-relaxed text-muted-foreground">{STATUS[status].meaning}</dd>
          </div>
        ))}
      </dl>

      <RetractionAlert report={report} />

      {error && (
        <p role="alert" className="mt-4 text-sm text-rose">
          {error}
        </p>
      )}
      <p className="mt-4 border-t border-divider pt-3.5 text-xs leading-relaxed text-subtle-foreground">
        Searched Crossref, OpenAlex, arXiv, JMLR and NeurIPS proceedings. Retraction and correction notices come from
        Crossref and the Retraction Watch database. A reference that is not found is not proof that it was made up.
      </p>
    </section>
  );
}

type Load = { status: "loading" } | { status: "ready" } | { status: "error"; message: string };

function needsReview(item: ReferenceItem) {
  return item.status !== "verified" || (item.notices ?? []).length > 0;
}

export function ReferencesPanel({ paperId }: { paperId: string }) {
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [report, setReport] = useState<ReferenceCheckResponse | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("review");

  function show(next: ReferenceCheckResponse | null) {
    setReport(next);
    if (next) setFilter(next.items.some(needsReview) ? "review" : "all");
  }

  // Show the saved result only. A new check makes many outside lookups, so it
  // starts from a button, never on its own.
  useEffect(() => {
    let cancelled = false;
    getSavedReferenceCheck(paperId)
      .then((saved) => {
        if (cancelled) return;
        show(saved);
        setLoad({ status: "ready" });
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoad({ status: "error", message: errorMessage(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [paperId, attempt]);

  // A report saved before the retraction alert existed gets it added quietly:
  // only the notices are looked up, not the references themselves.
  useEffect(() => {
    if (!report || report.notices_checked || report.total === 0 || checking) return;
    if (report.items.some((item) => item.status === "unavailable")) return;
    let cancelled = false;
    checkReferences(paperId, false)
      .then((res) => {
        if (!cancelled) show(res);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
    // Run once per loaded report.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paperId, report?.checked_at]);

  function runCheck(force: boolean) {
    if (checking) return;
    setCheckError(null);
    setChecking(true);
    checkReferences(paperId, force)
      .then(show)
      .catch((err: unknown) => setCheckError(errorMessage(err)))
      .finally(() => setChecking(false));
  }

  if (load.status === "loading") {
    return (
      <div className="flex flex-col gap-4" aria-busy="true">
        <span className="sr-only">Loading the reference check</span>
        <Skeleton className="h-44 w-full rounded-xl" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
    );
  }

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
        title="Are this paper's references real?"
        action="Check references"
        busyAction="Checking references…"
        timing="This usually takes about a minute, or a few minutes for a paper with hundreds of references."
        busyTiming="Looking up each reference. This usually takes about a minute, or a few minutes for a paper with hundreds of references."
        checking={checking}
        error={checkError}
        onStart={() => runCheck(false)}
      >
        ReSense looks up every entry in the reference list in Crossref, OpenAlex, arXiv and publisher records, shows which
        ones match a published work and which need a closer look, and warns you if a cited work has since been retracted
        or corrected.
      </StartCard>
    );
  }

  if (report.total === 0) {
    return (
      <div className="rounded-xl border border-border bg-card px-6 py-8 text-center">
        <p className="text-sm text-muted-foreground">
          We couldn&apos;t find a reference list in this paper, so there was nothing to check.
        </p>
      </div>
    );
  }

  const toReview = report.items.filter(needsReview).length;
  const filters: { id: Filter; label: string; count: number }[] = [
    { id: "all", label: "All", count: report.total },
    { id: "review", label: "To review", count: toReview },
    { id: "matched", label: "Matched", count: report.verified },
  ];
  const visible = GROUP_ORDER.filter((status) =>
    filter === "all" ? true : filter === "matched" ? status === "verified" : true
  );
  const shown = (status: ReferenceStatus) =>
    report.items.filter(
      (item) => item.status === status && (filter !== "review" || needsReview(item))
    );

  return (
    <div>
      <Summary report={report} checking={checking} error={checkError} onCheckAgain={() => runCheck(true)} />
      <p className="sr-only" role="status" aria-live="polite">
        {checking ? "Checking every reference again. This can take a few minutes for a long reference list." : ""}
      </p>

      <FilterChips label="Show references" options={filters} value={filter} onChange={setFilter} />

      <div className={cn("mt-5 transition-opacity", checking && "opacity-60")}>
        {filter === "review" && toReview === 0 ? (
          <p className="rounded-xl border border-border bg-card px-5 py-6 text-sm text-muted-foreground">
            Nothing to review. Every reference matched a published record.
          </p>
        ) : (
          visible.map((status) => <Group key={status} status={status} items={shown(status)} />)
        )}
      </div>
    </div>
  );
}
