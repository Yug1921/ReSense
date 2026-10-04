"use client";

import { startTransition, useEffect, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { RotateCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { summarizePaper, ApiError, type Tone } from "@/lib/api";
import { ToneSelector } from "./tone-selector";
import { ProcessingScan } from "@/components/processing/processing-scan";

type Phase = "idle" | "scanning" | "ready" | "error";

type FetchState =
  | { status: "pending" }
  | { status: "success"; content: string }
  | { status: "error"; message: string };

function SummaryContent({ content }: { content: string }) {
  return (
    <div className="space-y-4 text-sm leading-relaxed text-zinc-200">
      {content.split("\n").map((line, index) => {
        const trimmedLine = line.trim();
        const isHeading =
          /^#{1,3}\s+/.test(trimmedLine) ||
          /^\d+(?:\.\d+)*\s+[A-Z][^.!?]*$/.test(trimmedLine);

        if (!trimmedLine) return <div key={index} className="h-1" aria-hidden="true" />;
        if (isHeading) {
          return (
            <h3 key={index} className="pt-2 text-base font-medium text-white">
              {trimmedLine.replace(/^#{1,3}\s+/, "")}
            </h3>
          );
        }
        return <p key={index}>{trimmedLine}</p>;
      })}
    </div>
  );
}

export interface SummaryPanelProps {
  paperId: string;
  className?: string;
}

export function SummaryPanel({ paperId, className }: SummaryPanelProps) {
  const [selectedTone, setSelectedTone] = useState<Tone | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [summaries, setSummaries] = useState<Partial<Record<Tone, string>>>({});

  const [scanDone, setScanDone] = useState(false);
  const [fetchState, setFetchState] = useState<FetchState>({ status: "pending" });

  useEffect(() => {
    if (phase !== "scanning") return;
    if (!scanDone || fetchState.status === "pending") return;

    if (fetchState.status === "success" && selectedTone) {
      console.log("[SummaryPanel] both scan + fetch done — revealing summary");
      startTransition(() => {
        setSummaries((prev) => ({ ...prev, [selectedTone]: fetchState.content }));
        setPhase("ready");
      });
    } else if (fetchState.status === "error") {
      console.error("[SummaryPanel] revealing error:", fetchState.message);
      startTransition(() => {
        setErrorMessage(fetchState.message);
        setPhase("error");
      });
    }
  }, [phase, scanDone, fetchState, selectedTone]);

  function handleGenerate(refresh = false) {
    if (!selectedTone) return;

    if (summaries[selectedTone] && !refresh) {
      setPhase("ready");
      return;
    }

    console.log("[SummaryPanel] generate clicked — tone:", selectedTone, "paperId:", paperId);
    setErrorMessage(null);
    setScanDone(false);
    setFetchState({ status: "pending" });
    setPhase("scanning");

    summarizePaper(paperId, selectedTone, refresh)
      .then((res) => {
        console.log("[SummaryPanel] /summarize resolved:", res);
        setFetchState({ status: "success", content: res.content });
      })
      .catch((err: unknown) => {
        console.error("[SummaryPanel] /summarize rejected:", err);
        const message =
          err instanceof ApiError ? err.message : "Something went wrong generating this summary.";
        setFetchState({ status: "error", message });
      });
  }

  function handleScanComplete() {
    console.log("[SummaryPanel] scan animation finished");
    setScanDone(true);
  }

  const currentSummary = selectedTone ? summaries[selectedTone] : undefined;

  return (
    <div className={cn("flex w-full flex-col items-center gap-6", className)}>
      <ToneSelector
        value={selectedTone}
        onChange={(tone) => {
          setSelectedTone(tone);
          setPhase(summaries[tone] ? "ready" : "idle");
        }}
        disabled={phase === "scanning"}
      />

      <AnimatePresence mode="wait">
        {phase === "scanning" && (
          <motion.div
            key="scanning"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="py-6"
          >
            <ProcessingScan onComplete={handleScanComplete} />
          </motion.div>
        )}

        {phase === "idle" && selectedTone && (
          <motion.button
            key="generate"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            onClick={() => handleGenerate()}
            className="rounded-lg bg-blue-500 px-6 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-400"
          >
            Generate Summary
          </motion.button>
        )}

        {phase === "error" && (
          <motion.div
            key="error"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex flex-col items-center gap-3 text-center"
          >
            <p className="text-sm text-red-400">{errorMessage}</p>
            <button
              onClick={() => handleGenerate()}
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-4 py-2 text-sm text-zinc-300 hover:bg-white/5"
            >
              <RotateCw className="h-3.5 w-3.5" />
              Try again
            </button>
          </motion.div>
        )}

        {phase === "ready" && currentSummary && (
          <motion.div
            key={`summary-${selectedTone}`}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.3 }}
            className="w-full max-w-4xl rounded-xl border border-white/10 bg-white/[0.02] p-6"
          >
            <SummaryContent content={currentSummary} />
            <div className="mt-4 flex items-center gap-4">
              <button
                onClick={() => handleGenerate(true)}
                className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-zinc-300"
              >
                <RotateCw className="h-3 w-3" />
                Regenerate summary
              </button>
              <button
                onClick={() => setSelectedTone(null)}
                className="text-xs text-muted-foreground hover:text-zinc-300"
              >
                Try a different tone
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default SummaryPanel;