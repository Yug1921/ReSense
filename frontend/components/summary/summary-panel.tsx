"use client";

import { useCallback, useRef, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { RotateCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { summarizePaper, ApiError, type Tone } from "@/lib/api";
import { ToneSelector } from "./tone-selector";
import { ProcessingScan } from "@/components/processing/processing-scan";

type Phase = "idle" | "scanning" | "ready" | "error";

export interface SummaryPanelProps {
  paperId: string;
  className?: string;
}

export function SummaryPanel({ paperId, className }: SummaryPanelProps) {
  const [selectedTone, setSelectedTone] = useState<Tone | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [currentSummary, setCurrentSummary] = useState<string | undefined>();

  // Local cache: once a tone's summary has been generated this session,
  // re-selecting it shows instantly — no re-running the scan animation
  // for something we (and the backend) already have.
  const summaryCache = useRef<Partial<Record<Tone, string>>>({});

  // Two independent completion signals — the scan animation and the real
  // network call — both must finish before we reveal the result, so the
  // animation never gets cut short by a fast response, and a slow response
  // never leaves the scan hanging with nothing to show afterward.
  const scanFinishedRef = useRef(false);
  const fetchResultRef = useRef<{ content: string } | { error: string } | null>(null);

  const tryReveal = useCallback((tone: Tone) => {
    if (!scanFinishedRef.current || !fetchResultRef.current) return;
    const result = fetchResultRef.current;
    if ("error" in result) {
      setErrorMessage(result.error);
      setPhase("error");
    } else {
      summaryCache.current[tone] = result.content;
      setCurrentSummary(result.content);
      setPhase("ready");
    }
  }, []);

  const handleGenerate = useCallback(() => {
    if (!selectedTone) return;

    const cached = summaryCache.current[selectedTone];
    if (cached) {
      setCurrentSummary(cached);
      setPhase("ready");
      return;
    }

    setErrorMessage(null);
    scanFinishedRef.current = false;
    fetchResultRef.current = null;
    setPhase("scanning");

    summarizePaper(paperId, selectedTone)
      .then((res) => {
        fetchResultRef.current = { content: res.content };
        tryReveal(selectedTone);
      })
      .catch((err: unknown) => {
        const message = err instanceof ApiError ? err.message : "Something went wrong generating this summary.";
        fetchResultRef.current = { error: message };
        tryReveal(selectedTone);
      });
  }, [paperId, selectedTone, tryReveal]);

  const handleScanComplete = useCallback(() => {
    scanFinishedRef.current = true;
    if (selectedTone) tryReveal(selectedTone);
  }, [selectedTone, tryReveal]);

  return (
    <div className={cn("flex w-full flex-col items-center gap-6", className)}>
      <ToneSelector
        value={selectedTone}
        onChange={(tone) => {
          setSelectedTone(tone);
          const cached = summaryCache.current[tone];
          setCurrentSummary(cached);
          setPhase(cached ? "ready" : "idle");
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
            className="w-full max-w-2xl rounded-xl border border-white/10 bg-white/[0.02] p-6"
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