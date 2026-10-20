"use client";

import { useState } from "react";
import { motion } from "motion/react";
import { ExternalLink, Loader2, RotateCw, ShieldCheck } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  checkReferences,
  ApiError,
  type PublicationRelation,
  type ReferenceCheckResponse,
  type ReferenceItem,
  type ReferenceStatus,
} from "@/lib/api";

type Phase = "idle" | "checking" | "ready" | "error";
type Filter = "all" | ReferenceStatus;

const STATUS_META: Record<ReferenceStatus, { label: string; hint: string; badge: string; dot: string }> = {
  verified: {
    label: "Verified",
    hint: "Matched a published record",
    badge: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
    dot: "bg-emerald-400",
  },
  uncertain: {
    label: "Needs review",
    hint: "Partial match or conflicting details",
    badge: "border-amber-500/30 bg-amber-500/10 text-amber-300",
    dot: "bg-amber-400",
  },
  not_found: {
    label: "Not found",
    hint: "No match in the sources searched",
    badge: "border-red-500/30 bg-red-500/10 text-red-300",
    dot: "bg-red-400",
  },
  unavailable: {
    label: "Couldn't check",
    hint: "A source was down or rate-limited",
    badge: "border-zinc-500/30 bg-zinc-500/10 text-zinc-300",
    dot: "bg-zinc-400",
  },
};

const STATUS_ORDER: ReferenceStatus[] = ["verified", "uncertain", "not_found", "unavailable"];

const RELATION_LABELS: Record<PublicationRelation, string> = {
  exact: "Exact match",
  same_work_version: "Same work, different version",
  possible_related: "Possibly a related work",
  different_work: "Different work",
};

const SOURCE_LABELS: Record<string, string> = {
  crossref: "Crossref",
  openalex: "OpenAlex",
  arxiv: "arXiv",
  jmlr: "JMLR",
  neurips: "NeurIPS",
};

function ReferenceRow({ item }: { item: ReferenceItem }) {
  const [expanded, setExpanded] = useState(false);
  const meta = STATUS_META[item.status];
  const showMatch = item.matched_title && item.status !== "not_found";

  return (
    <li className="rounded-lg border border-white/10 bg-white/[0.02] p-4">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 w-7 shrink-0 text-right font-mono text-xs text-zinc-500">[{item.index}]</span>
        <div className="min-w-0 flex-1 space-y-2">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className={cn(
              "block w-full text-left text-sm text-zinc-200",
              !expanded && "line-clamp-2"
            )}
            title={expanded ? "Show less" : "Show full reference"}
          >
            {item.raw.replace(/^\s*\[\d+\]\s*/, "")}
          </button>

          {showMatch && (
            <p className="text-xs text-zinc-400">
              <span className="text-zinc-500">Matched: </span>
              {item.matched_title}
              {item.matched_year ? ` (${item.matched_year})` : ""}
              {item.matched_doi && (
                <a
                  href={`https://doi.org/${item.matched_doi}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="ml-2 inline-flex items-center gap-0.5 text-blue-400 hover:text-blue-300"
                >
                  DOI <ExternalLink className="h-3 w-3" />
                </a>
              )}
            </p>
          )}

          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-zinc-500">
            {item.source && <span>Source: {SOURCE_LABELS[item.source] ?? item.source}</span>}
            {item.publication_relation && <span>{RELATION_LABELS[item.publication_relation]}</span>}
            {item.status !== "unavailable" && item.similarity > 0 && (
              <span>Title similarity {Math.round(item.similarity * 100)}%</span>
            )}
          </div>

          {item.conflict_fields.length > 0 && (
            <p className="text-xs text-amber-300/90">Differs in: {item.conflict_fields.join(", ")}</p>
          )}
          {item.match_reason && <p className="text-xs text-zinc-500">{item.match_reason}</p>}
          {item.error && <p className="text-xs text-zinc-500">{item.error}</p>}
        </div>
        <span className={cn("shrink-0 rounded-full border px-2.5 py-0.5 text-xs", meta.badge)}>{meta.label}</span>
      </div>
    </li>
  );
}

export interface IntegrityPanelProps {
  paperId: string;
  className?: string;
}

export function IntegrityPanel({ paperId, className }: IntegrityPanelProps) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [report, setReport] = useState<ReferenceCheckResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");

  // Triggered by a button rather than an effect: a check makes many external
  // lookups, and Strict Mode would double-fire an effect in development.
  function runCheck(force = false) {
    if (phase === "checking") return;
    setErrorMessage(null);
    setPhase("checking");
    checkReferences(paperId, force)
      .then((res) => {
        setReport(res);
        setFilter("all");
        setPhase("ready");
      })
      .catch((err: unknown) => {
        const message = err instanceof ApiError ? err.message : "Couldn't check this paper's references.";
        setErrorMessage(message);
        setPhase(report ? "ready" : "error");
      });
  }

  const visibleItems = report
    ? filter === "all"
      ? report.items
      : report.items.filter((item) => item.status === filter)
    : [];

  return (
    <div className={cn("flex w-full flex-col gap-6", className)}>
      <div className="rounded-xl border border-white/10 bg-white/[0.02] p-6">
        <div className="flex items-start gap-3">
          <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-blue-400" />
          <div className="space-y-1">
            <h2 className="text-base font-medium text-white">Reference check</h2>
            <p className="text-sm text-muted-foreground">
              Each reference in the bibliography is looked up in Crossref, arXiv, OpenAlex and publisher
              records. A reference that is not found is flagged for review; it is not proof that the
              reference was fabricated, since many real works are missing from these sources.
            </p>
          </div>
        </div>

        {phase === "idle" && (
          <button
            type="button"
            onClick={() => runCheck()}
            className="mt-5 rounded-lg bg-blue-500 px-6 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-400"
          >
            Check references
          </button>
        )}

        {phase === "checking" && (
          <p className="mt-5 inline-flex items-center gap-2 text-sm text-zinc-300">
            <Loader2 className="h-4 w-4 animate-spin" />
            Checking references. This can take a minute for a long bibliography.
          </p>
        )}

        {phase === "error" && (
          <div className="mt-5 flex flex-col items-start gap-3">
            <p className="text-sm text-red-400">{errorMessage}</p>
            <button
              type="button"
              onClick={() => runCheck()}
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-4 py-2 text-sm text-zinc-300 hover:bg-white/5"
            >
              <RotateCw className="h-3.5 w-3.5" />
              Try again
            </button>
          </div>
        )}
      </div>

      {report && phase !== "idle" && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
          className="flex flex-col gap-6"
        >
          {report.total === 0 ? (
            <p className="text-sm text-muted-foreground">
              No references could be found in this paper&apos;s text, so nothing was checked.
            </p>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {STATUS_ORDER.map((status) => {
                  const meta = STATUS_META[status];
                  const active = filter === status;
                  return (
                    <button
                      key={status}
                      type="button"
                      onClick={() => setFilter(active ? "all" : status)}
                      className={cn(
                        "rounded-xl border p-4 text-left transition-colors",
                        active ? "border-white/30 bg-white/[0.06]" : "border-white/10 bg-white/[0.02] hover:bg-white/[0.04]"
                      )}
                    >
                      <div className="flex items-center gap-2 text-xs text-zinc-400">
                        <span className={cn("h-2 w-2 rounded-full", meta.dot)} />
                        {meta.label}
                      </div>
                      <div className="mt-1 text-2xl font-semibold text-white">{report[status]}</div>
                      <div className="mt-0.5 text-xs text-zinc-500">{meta.hint}</div>
                    </button>
                  );
                })}
              </div>

              <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground">
                <span>
                  {filter === "all"
                    ? `All ${report.total} references`
                    : `${visibleItems.length} of ${report.total} references: ${STATUS_META[filter].label.toLowerCase()}`}
                  {filter !== "all" && (
                    <button type="button" onClick={() => setFilter("all")} className="ml-2 text-blue-400 hover:text-blue-300">
                      Show all
                    </button>
                  )}
                </span>
                <span className="inline-flex items-center gap-3">
                  {report.cached && <span>Saved result from an earlier check.</span>}
                  <button
                    type="button"
                    onClick={() => runCheck(true)}
                    disabled={phase === "checking"}
                    className="inline-flex items-center gap-1.5 hover:text-zinc-300 disabled:opacity-50"
                  >
                    <RotateCw className="h-3 w-3" />
                    Check again
                  </button>
                </span>
              </div>

              {errorMessage && <p className="text-sm text-red-400">{errorMessage}</p>}

              <ul className="flex flex-col gap-3">
                {visibleItems.map((item) => (
                  <ReferenceRow key={item.index} item={item} />
                ))}
              </ul>
            </>
          )}
        </motion.div>
      )}
    </div>
  );
}

export default IntegrityPanel;
