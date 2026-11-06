"use client";

import { useState, type KeyboardEvent } from "react";
import { BookCheck, Link2, Quote } from "lucide-react";
import { cn } from "@/lib/utils";
import { ReferencesPanel } from "@/components/integrity/references-panel";
import { ClaimsPanel } from "@/components/integrity/claims-panel";
import { LinksPanel } from "@/components/integrity/links-panel";

const CHECKS = [
  { id: "references", label: "References", short: "References", hint: "Are they real? Retracted?", icon: BookCheck },
  { id: "claims", label: "Claims", short: "Claims", hint: "Do sources say that?", icon: Quote },
  { id: "links", label: "Links & data", short: "Links", hint: "Can it be reproduced?", icon: Link2 },
] as const;

type CheckId = (typeof CHECKS)[number]["id"];

/** The Integrity tab: three checks, each started on its own and saved with the paper. */
export function IntegrityPanel({ paperId }: { paperId: string }) {
  const [active, setActive] = useState<CheckId>("references");

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const index = CHECKS.findIndex((check) => check.id === active);
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const next = CHECKS[(index + step + CHECKS.length) % CHECKS.length].id;
    setActive(next);
    document.getElementById(`check-${next}`)?.focus();
  }

  return (
    <div className="mx-auto max-w-5xl">
      <div
        role="tablist"
        aria-label="Integrity checks"
        onKeyDown={onKeyDown}
        className="mb-6 grid grid-cols-3 gap-1 rounded-xl border border-border bg-card p-1"
      >
        {CHECKS.map((check) => {
          const selected = check.id === active;
          const Icon = check.icon;
          return (
            <button
              key={check.id}
              id={`check-${check.id}`}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-controls={`check-panel-${check.id}`}
              tabIndex={selected ? 0 : -1}
              onClick={() => setActive(check.id)}
              className={cn(
                "flex min-w-0 items-center justify-center gap-2 rounded-lg px-2 py-2 text-left transition-colors sm:justify-start sm:px-3.5 sm:py-2.5",
                selected ? "bg-raised text-heading" : "text-muted-foreground hover:bg-raised/50 hover:text-heading"
              )}
            >
              <Icon className={cn("size-4 shrink-0", selected ? "text-iris" : "")} aria-hidden />
              <span className="min-w-0">
                <span className="block truncate text-[13px] font-medium sm:text-sm">
                  <span className="sm:hidden">{check.short}</span>
                  <span className="hidden sm:inline">{check.label}</span>
                </span>
                <span className="hidden truncate text-xs text-subtle-foreground sm:block">{check.hint}</span>
              </span>
            </button>
          );
        })}
      </div>

      {CHECKS.map((check) => (
        <section
          key={check.id}
          id={`check-panel-${check.id}`}
          role="tabpanel"
          aria-labelledby={`check-${check.id}`}
          hidden={check.id !== active}
        >
          {check.id === "references" && <ReferencesPanel paperId={paperId} />}
          {check.id === "claims" && <ClaimsPanel paperId={paperId} onOpenReferences={() => setActive("references")} />}
          {check.id === "links" && <LinksPanel paperId={paperId} />}
        </section>
      ))}
    </div>
  );
}

export default IntegrityPanel;
