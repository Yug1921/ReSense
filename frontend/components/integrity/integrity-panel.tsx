"use client";

import { useEffect, useId, useState, type ReactNode } from "react";
import { ChevronDown, ExternalLink, Loader2, RotateCw, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  ApiError,
  checkReferences,
  getSavedReferenceCheck,
  type ReferenceCheckResponse,
  type ReferenceItem,
  type ReferenceStatus,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

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

function checkedLine(iso: string | null) {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return "Checked today";
  if (date.toDateString() === yesterday.toDateString()) return "Checked yesterday";
  return `Checked on ${date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}`;
}

function errorMessage(err: unknown) {
  if (err instanceof ApiError) {
    if (err.status === 0) return "We couldn't reach ReSense. Check your connection and try again.";
    return err.message;
  }
  return "We couldn't check this paper's references. Try again.";
}

function Num({ children }: { children: ReactNode }) {
  return <span className="figures">{children}</span>;
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

function ElapsedTime() {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setSeconds((value) => value + 1), 1000);
    return () => clearInterval(timer);
  }, []);
  return <span className="figures">{`${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`}</span>;
}

function ReferenceRow({ item }: { item: ReferenceItem }) {
  const [open, setOpen] = useState(false);
  const detailsId = useId();
  const { chip, text } = explain(item);
  const meta = STATUS[item.status];
  const line = citeLine(item);
  const showRecord = item.matched_title && (item.status === "verified" || item.status === "uncertain");
  const source = item.source ? SOURCE_LABELS[item.source] ?? item.source : null;
  const chipBadge = chip && <Badge tone={meta.tone}>{chip}</Badge>;

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

      {error && (
        <p role="alert" className="mt-4 text-sm text-rose">
          {error}
        </p>
      )}
      <p className="mt-4 border-t border-divider pt-3.5 text-xs leading-relaxed text-subtle-foreground">
        Searched Crossref, OpenAlex, arXiv, JMLR and NeurIPS proceedings. A reference that is not found is not proof that
        it was made up.
      </p>
    </section>
  );
}

type Load = { status: "loading" } | { status: "ready" } | { status: "error"; message: string };

export function IntegrityPanel({ paperId }: { paperId: string }) {
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [report, setReport] = useState<ReferenceCheckResponse | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("review");

  // Show the saved result only. A new check makes many outside lookups, so it
  // starts from a button, never on its own.
  useEffect(() => {
    let cancelled = false;
    getSavedReferenceCheck(paperId)
      .then((saved) => {
        if (cancelled) return;
        setReport(saved);
        if (saved) setFilter(saved.verified === saved.total ? "all" : "review");
        setLoad({ status: "ready" });
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoad({ status: "error", message: errorMessage(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [paperId, attempt]);

  function runCheck(force: boolean) {
    if (checking) return;
    setCheckError(null);
    setChecking(true);
    checkReferences(paperId, force)
      .then((res) => {
        setReport(res);
        setFilter(res.verified === res.total ? "all" : "review");
      })
      .catch((err: unknown) => setCheckError(errorMessage(err)))
      .finally(() => setChecking(false));
  }

  if (load.status === "loading") {
    return (
      <div className="mx-auto flex max-w-5xl flex-col gap-4" aria-busy="true">
        <span className="sr-only">Loading the reference check</span>
        <Skeleton className="h-44 w-full rounded-xl" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
    );
  }

  if (load.status === "error") {
    return (
      <div className="mx-auto flex max-w-md flex-col items-center gap-3 py-16 text-center">
        <p className="text-sm text-muted-foreground">{load.message}</p>
        <Button
          size="sm"
          onClick={() => {
            setLoad({ status: "loading" });
            setAttempt((value) => value + 1);
          }}
        >
          Try again
        </Button>
      </div>
    );
  }

  if (!report) {
    return (
      <div className="mx-auto max-w-5xl">
        <section className="rounded-xl border border-border bg-card px-5 py-6 sm:px-7 sm:py-7">
          <p className="eyebrow">Reference check</p>
          <h2 className="mt-2 text-xl font-semibold">Are this paper&apos;s references real?</h2>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">
            ReSense looks up every entry in the reference list in Crossref, OpenAlex, arXiv and publisher records, and
            shows which ones match a published work and which ones need a closer look.
          </p>
          <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-2">
            <Button variant="primary" onClick={() => runCheck(false)} disabled={checking}>
              {checking && <Loader2 className="animate-spin" aria-hidden />}
              {checking ? "Checking references…" : "Check references"}
            </Button>
            <span className="text-xs text-subtle-foreground" role="status" aria-live="polite">
              {checking ? (
                <>
                  Looking up each reference. A long list takes about a minute. <ElapsedTime />
                </>
              ) : (
                "A long reference list takes about a minute."
              )}
            </span>
          </div>
          {checking && (
            <div aria-hidden className="mt-5 h-1 overflow-hidden rounded-full bg-raised">
              <div className="h-full w-1/3 animate-scan rounded-full bg-iris/70" />
            </div>
          )}
          {checkError && (
            <p role="alert" className="mt-4 text-sm text-rose">
              {checkError}
            </p>
          )}
        </section>
      </div>
    );
  }

  if (report.total === 0) {
    return (
      <div className="mx-auto max-w-5xl rounded-xl border border-border bg-card px-6 py-8 text-center">
        <p className="text-sm text-muted-foreground">
          We couldn&apos;t find a reference list in this paper, so there was nothing to check.
        </p>
      </div>
    );
  }

  const toReview = report.total - report.verified;
  const filters: { id: Filter; label: string; count: number }[] = [
    { id: "all", label: "All", count: report.total },
    { id: "review", label: "To review", count: toReview },
    { id: "matched", label: "Matched", count: report.verified },
  ];
  const visible = GROUP_ORDER.filter((status) =>
    filter === "all" ? true : filter === "matched" ? status === "verified" : status !== "verified"
  );

  return (
    <div className="mx-auto max-w-5xl">
      <Summary report={report} checking={checking} error={checkError} onCheckAgain={() => runCheck(true)} />
      <p className="sr-only" role="status" aria-live="polite">
        {checking ? "Checking every reference again. This can take about a minute." : ""}
      </p>

      <div role="group" aria-label="Show references" className="mt-6 flex flex-wrap gap-2">
        {filters.map((option) => {
          const active = filter === option.id;
          return (
            <button
              key={option.id}
              type="button"
              aria-pressed={active}
              onClick={() => setFilter(option.id)}
              className={cn(
                "h-8 rounded-full border px-3.5 text-[13px] transition-colors",
                active
                  ? "border-border-strong bg-raised text-heading"
                  : "border-border text-muted-foreground hover:border-border-strong hover:text-heading"
              )}
            >
              {option.label}{" "}
              <span className="figures ml-1">{option.count}</span>
            </button>
          );
        })}
      </div>

      <div className={cn("mt-5 transition-opacity", checking && "opacity-60")}>
        {filter === "review" && toReview === 0 ? (
          <p className="rounded-xl border border-border bg-card px-5 py-6 text-sm text-muted-foreground">
            Nothing to review. Every reference matched a published record.
          </p>
        ) : (
          visible.map((status) => (
            <Group key={status} status={status} items={report.items.filter((item) => item.status === status)} />
          ))
        )}
      </div>
    </div>
  );
}

export default IntegrityPanel;
