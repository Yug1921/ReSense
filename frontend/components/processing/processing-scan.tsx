"use client";

import { useEffect, useMemo, useState } from "react";
import { motion } from "motion/react";
import { FileText, Image as ImageIcon, Sigma, Table2, Check, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

interface ScanCategory {
  id: string;
  label: string;
  icon: LucideIcon;
}

const CATEGORIES: ScanCategory[] = [
  { id: "text", label: "Text", icon: FileText },
  { id: "images", label: "Images", icon: ImageIcon },
  { id: "formulas", label: "Formulas", icon: Sigma },
  { id: "tables", label: "Tables", icon: Table2 },
];

// Total sweep ≈ CATEGORIES.length * MS_PER_CARD. Tuned short on purpose —
// the original template's scan was slow/for endless browsing; this needs
// to read as "fast, active work happening" for a few-second wait.
const MS_PER_CARD = 650;

const SCRAMBLE_CHARS =
  "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789(){}[]<>;:,._-+=!@#$%^&*|/?";

function randomScramble(length: number): string {
  let out = "";
  for (let i = 0; i < length; i++) {
    out += SCRAMBLE_CHARS[Math.floor(Math.random() * SCRAMBLE_CHARS.length)];
  }
  return out;
}

/** Cycles a short block of random "code-like" characters while `active` is true. */
function useScrambleText(active: boolean, length = 26): string {
  const [text, setText] = useState<string>(() => randomScramble(length));

  useEffect(() => {
    if (!active) return;
    const interval = setInterval(() => setText(randomScramble(length)), 55);
    return () => clearInterval(interval);
  }, [active, length]);

  return text;
}

type CardStatus = "pending" | "scanning" | "done";

function ScanCard({ category, status }: { category: ScanCategory; status: CardStatus }) {
  const Icon = category.icon;
  const scramble = useScrambleText(status === "scanning");

  return (
    <div
      className={cn(
        "relative flex h-40 w-40 flex-col items-center justify-center gap-3 overflow-hidden rounded-xl border transition-colors duration-300",
        status === "pending" && "border-white/10 bg-white/[0.02]",
        status === "scanning" && "border-blue-500/40 bg-blue-500/[0.06]",
        status === "done" && "border-emerald-500/30 bg-emerald-500/[0.05]"
      )}
    >
      {status === "scanning" && (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 flex flex-wrap content-center justify-center gap-0.5 overflow-hidden p-3 font-mono text-[9px] leading-tight text-blue-400/40"
        >
          {scramble}
        </div>
      )}

      <div className="relative z-10 flex flex-col items-center gap-2">
        {status === "done" ? (
          <Check className="h-7 w-7 text-emerald-400" />
        ) : (
          <Icon
            className={cn(
              "h-7 w-7 transition-colors duration-300",
              status === "pending" && "text-white/25",
              status === "scanning" && "text-blue-400"
            )}
          />
        )}
        <span
          className={cn(
            "text-xs font-medium transition-colors duration-300",
            status === "pending" && "text-white/30",
            status === "scanning" && "text-blue-300",
            status === "done" && "text-emerald-300"
          )}
        >
          {category.label}
        </span>
      </div>
    </div>
  );
}

export interface ProcessingScanProps {
  /** Called once the full sweep across all categories has finished. */
  onComplete?: () => void;
  className?: string;
}

/**
 * Part 2 — the "scanning the paper" loading screen shown between clicking
 * Generate Summary and the response landing. Adapted from the card-scan-
 * carousel template's visual language (a sweeping scanline that reveals
 * code-like content) but rebuilt as a finite, React-state-driven sequence
 * instead of the original's infinite draggable carousel + WebGL particle
 * system — this only ever needs to play once, for four fixed categories.
 */
export function ProcessingScan({ onComplete, className }: ProcessingScanProps) {
  const [activeIndex, setActiveIndex] = useState(0); // index of the card currently "scanning"
  const totalDuration = CATEGORIES.length * MS_PER_CARD;

  useEffect(() => {
    if (activeIndex >= CATEGORIES.length) {
      const doneTimer = setTimeout(() => onComplete?.(), 300);
      return () => clearTimeout(doneTimer);
    }
    const timer = setTimeout(() => setActiveIndex((i) => i + 1), MS_PER_CARD);
    return () => clearTimeout(timer);
  }, [activeIndex, onComplete]);

  const statuses: CardStatus[] = useMemo(
    () =>
      CATEGORIES.map((_, i) =>
        i < activeIndex ? "done" : i === activeIndex ? "scanning" : "pending"
      ),
    [activeIndex]
  );

  return (
    <div className={cn("flex flex-col items-center gap-8", className)}>
      <div className="relative flex gap-5">
        {CATEGORIES.map((category, i) => (
          <ScanCard key={category.id} category={category} status={statuses[i]} />
        ))}

        {/* Purely visual continuous sweep — glides across the row once,
            independent of the discrete per-card state above. */}
        <motion.div
          aria-hidden
          className="pointer-events-none absolute inset-y-0 w-px bg-gradient-to-b from-transparent via-blue-400 to-transparent shadow-[0_0_12px_2px_rgba(96,165,250,0.6)]"
          initial={{ left: "0%" }}
          animate={{ left: "100%" }}
          transition={{ duration: totalDuration / 1000, ease: "linear" }}
        />
      </div>

      <p className="text-sm text-muted-foreground">
        Scanning paper contents — text, images, formulas, and tables&hellip;
      </p>
    </div>
  );
}

export default ProcessingScan;