import { cn } from "@/lib/utils";

const TONES = {
  sage: "bg-sage",
  honey: "bg-honey",
  rose: "bg-rose",
  slate: "bg-slate",
  iris: "bg-iris",
} as const;

export type StatusTone = keyof typeof TONES;

// Colour is never the only signal: always pair the dot with a word.
export function StatusDot({ tone, className }: { tone: StatusTone; className?: string }) {
  return <span aria-hidden className={cn("inline-block size-2 shrink-0 rounded-full", TONES[tone], className)} />;
}
