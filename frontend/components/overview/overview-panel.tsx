"use client";

import { useEffect, useState, type ReactNode } from "react";
import { ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { analyzePaper, ApiError, type AnalyzeResponse } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { InfoTip } from "@/components/ui/info-tip";
import { Skeleton } from "@/components/ui/skeleton";

const WORDS_PER_MINUTE = 250;
const BACK_MATTER = new Set(["References", "Appendix", "Acknowledgments", "Acknowledgements"]);

const PAPER_TYPES: Record<string, { label: string; phrase: string }> = {
  empirical: { label: "Empirical study", phrase: "An empirical study" },
  theoretical: { label: "Theoretical paper", phrase: "A theoretical paper" },
  survey: { label: "Survey", phrase: "A survey" },
  case_study: { label: "Case study", phrase: "A case study" },
};

// From the backend's 1-10 score (length, sections and technical terms).
function readingLevel(score: number) {
  if (score <= 4) return { label: "Introductory", filled: 1 };
  if (score <= 6) return { label: "Intermediate", filled: 2 };
  return { label: "Advanced", filled: 3 };
}

function roundWords(count: number) {
  return (count >= 1000 ? Math.round(count / 100) * 100 : count).toLocaleString("en-US");
}

type Phase = { kind: "loading" } | { kind: "ready"; data: AnalyzeResponse } | { kind: "error"; message: string };

export interface OverviewPanelProps {
  paperId: string;
  wordCount?: number;
  initialAnalysis?: AnalyzeResponse | null;
  onOpenTab: (tab: "summary" | "integrity") => void;
}

export function OverviewPanel({ paperId, wordCount, initialAnalysis, onOpenTab }: OverviewPanelProps) {
  const [phase, setPhase] = useState<Phase>(
    initialAnalysis ? { kind: "ready", data: initialAnalysis } : { kind: "loading" }
  );
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (initialAnalysis && attempt === 0) return;
    let cancelled = false;
    analyzePaper(paperId)
      .then((data) => {
        if (!cancelled) setPhase({ kind: "ready", data });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setPhase({
          kind: "error",
          message: err instanceof ApiError && err.status !== 0 ? err.message : "We couldn't load the overview. Try again.",
        });
      });
    return () => {
      cancelled = true;
    };
  }, [paperId, initialAnalysis, attempt]);

  if (phase.kind === "loading") {
    return (
      <div aria-busy="true">
        <p className="text-sm text-muted-foreground" role="status">
          Looking at the paper&apos;s structure…
        </p>
        <div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-28 rounded-xl" />
          ))}
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-[1.4fr_1fr]">
          <Skeleton className="h-72 rounded-xl" />
          <Skeleton className="h-72 rounded-xl" />
        </div>
      </div>
    );
  }

  if (phase.kind === "error") {
    return (
      <Card className="flex flex-col items-start gap-3 p-6">
        <p className="text-sm text-foreground">{phase.message}</p>
        <Button
          size="sm"
          onClick={() => {
            setPhase({ kind: "loading" });
            setAttempt((value) => value + 1);
          }}
        >
          Try again
        </Button>
      </Card>
    );
  }

  const { data } = phase;
  const type = PAPER_TYPES[data.classification?.paper_type ?? ""];
  const level = data.classification ? readingLevel(data.classification.complexity_score) : null;
  const bodySections = data.section_lengths.filter((s) => !BACK_MATTER.has(s.label));
  const largest = bodySections.reduce<(typeof bodySections)[number] | null>(
    (best, s) => (!best || s.value > best.value ? s : best),
    null
  );
  const maxWords = Math.max(1, ...data.section_lengths.map((s) => s.value));
  const terms = data.keywords.slice(0, 12);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-lg font-semibold">At a glance</h2>
        {wordCount ? (
          <p className="mt-1 text-[15px] leading-relaxed text-muted-foreground">
            {type ? type.phrase : "A paper"} of about {roundWords(wordCount)} words.
            {largest && <> Most of its length goes to the {largest.label} section.</>}
          </p>
        ) : null}
      </div>

      <div className={cn("grid grid-cols-2 gap-3", type ? "lg:grid-cols-4" : "lg:grid-cols-3")}>
        {type && (
          <Fact
            title="Paper type"
            tip="Estimated by AI from the paper's text. It can be wrong for unusual papers."
            value={type.label}
            note="Estimated by AI"
          />
        )}
        {level && (
          <Fact
            title="Reading level"
            tip="Worked out from the paper's length, how many sections it has, and how often it uses technical terms. It says nothing about quality."
            value={level.label}
            note={
              <span className="flex gap-1" aria-hidden>
                {[1, 2, 3].map((step) => (
                  <span
                    key={step}
                    className={cn("h-1.5 w-6 rounded-full", step <= level.filled ? "bg-iris" : "bg-border-strong")}
                  />
                ))}
              </span>
            }
          />
        )}
        {wordCount ? (
          <Fact
            title="Length"
            tip={`Counted from the text we extracted. Reading time assumes ${WORDS_PER_MINUTE} words a minute.`}
            value={`${wordCount.toLocaleString("en-US")} words`}
            note={`About ${Math.max(1, Math.round(wordCount / WORDS_PER_MINUTE))} min to read`}
          />
        ) : null}
        {data.reference_count != null && (
          <Fact
            title="References"
            tip="Entries found in the paper's reference list. The Integrity tab checks each one against published records."
            value={`${data.reference_count} cited`}
            note={
              data.reference_count > 0 ? (
                <button type="button" onClick={() => onOpenTab("integrity")} className="text-iris hover:text-iris-strong">
                  Check the references
                </button>
              ) : (
                "No reference list found"
              )
            }
          />
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <Card className="p-6">
          <h3 className="text-[15px] font-medium">Where the paper spends its words</h3>
          <p className="mt-1 text-[13px] text-subtle-foreground">Top-level sections found in the paper, in reading order.</p>
          {data.section_lengths.length > 0 ? (
            <ul className="mt-5 flex flex-col gap-3">
              {data.section_lengths.map((section) => {
                const back = BACK_MATTER.has(section.label);
                return (
                  <li key={section.label} className="grid grid-cols-[minmax(0,9rem)_1fr_3.5rem] items-center gap-3 sm:grid-cols-[minmax(0,11rem)_1fr_4rem]">
                    <span className={cn("truncate text-[13px]", back ? "text-muted-foreground" : "text-foreground")} title={section.label}>
                      {section.label}
                    </span>
                    <span className="h-2 overflow-hidden rounded-full bg-raised" aria-hidden>
                      <span
                        className={cn("block h-full rounded-full", back ? "bg-slate/60" : "bg-iris")}
                        style={{ width: `${Math.max(2, (section.value / maxWords) * 100)}%` }}
                      />
                    </span>
                    <span className="figures text-right text-[13px] text-muted-foreground">
                      {section.value.toLocaleString("en-US")}
                    </span>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="mt-5 text-sm text-muted-foreground">We couldn&apos;t find clear section headings in this paper.</p>
          )}
          <p className="mt-5 text-xs text-subtle-foreground">Words per section. References and appendix are shown in grey.</p>
        </Card>

        <Card className="p-6">
          <h3 className="text-[15px] font-medium">Key terms</h3>
          <p className="mt-1 text-[13px] text-subtle-foreground">The words this paper uses most, with common words left out.</p>
          <ul className="mt-5 flex flex-wrap gap-2">
            {terms.map((term) => (
              <li
                key={term.label}
                className="inline-flex items-center gap-2 rounded-full border border-border bg-background px-3 py-1 text-[13px] text-foreground"
              >
                {term.label}
                <span className="figures text-xs text-subtle-foreground">{term.value}</span>
              </li>
            ))}
          </ul>
          <p className="mt-5 text-xs text-subtle-foreground">The number is how many times the word appears.</p>
        </Card>
      </div>

      <Card className="flex flex-col items-start justify-between gap-4 border-iris/25 bg-iris/[0.06] p-5 sm:flex-row sm:items-center">
        <div>
          <p className="text-[15px] font-medium text-heading">New to this paper?</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Start with a Research Insight summary: the problem, what is new, and why it matters.
          </p>
        </div>
        <Button variant="primary" onClick={() => onOpenTab("summary")}>
          Read the summary
          <ArrowRight aria-hidden />
        </Button>
      </Card>
    </div>
  );
}

function Fact({ title, tip, value, note }: { title: string; tip: string; value: string; note: ReactNode }) {
  return (
    <Card className="flex flex-col gap-1.5 p-4">
      <div className="flex items-center gap-1 text-xs text-subtle-foreground">
        {title}
        <InfoTip label={`About ${title.toLowerCase()}`}>{tip}</InfoTip>
      </div>
      <p className="text-lg font-medium text-heading">{value}</p>
      <div className="text-xs text-subtle-foreground">{note}</div>
    </Card>
  );
}

export default OverviewPanel;
