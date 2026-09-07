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

  function handleGenerate() {
    if (!selectedTone) return;

    if (summaries[selectedTone]) {
      setPhase("ready");
      return;
    }

    console.log("[SummaryPanel] generate clicked — tone:", selectedTone, "paperId:", paperId);
    setErrorMessage(null);
    setScanDone(false);
    setFetchState({ status: "pending" });
    setPhase("scanning");

    summarizePaper(paperId, selectedTone)
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
            onClick={handleGenerate}
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
              onClick={handleGenerate}
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
            <div className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-200">
              {currentSummary}
            </div>
            <button
              onClick={() => setSelectedTone(null)}
              className="mt-4 text-xs text-muted-foreground hover:text-zinc-300"
            >
              Try a different tone
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default SummaryPanel;