"use client";

import { useEffect, useState, type ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function checkedLine(iso: string | null) {
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

export function errorMessage(err: unknown, fallback: string) {
  if (err instanceof ApiError) {
    if (err.status === 0) return "We couldn't reach ReSense. Check your connection and try again.";
    return err.message;
  }
  return fallback;
}

export function Num({ children }: { children: ReactNode }) {
  return <span className="figures">{children}</span>;
}

export function ElapsedTime() {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setSeconds((value) => value + 1), 1000);
    return () => clearInterval(timer);
  }, []);
  return <span className="figures">{`${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`}</span>;
}

/** The first-run card of a check: what it does, and a button to start it. */
export function StartCard({
  title,
  children,
  action,
  busyAction,
  timing,
  busyTiming,
  checking,
  disabled,
  error,
  onStart,
}: {
  title: string;
  children: ReactNode;
  action: string;
  busyAction: string;
  timing: string;
  busyTiming: string;
  checking: boolean;
  disabled?: boolean;
  error: string | null;
  onStart: () => void;
}) {
  return (
    <section className="rounded-xl border border-border bg-card px-5 py-6 sm:px-7 sm:py-7">
      <h2 className="text-xl font-semibold">{title}</h2>
      <div className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">{children}</div>
      <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-2">
        <Button variant="primary" onClick={onStart} disabled={checking || disabled}>
          {checking && <Loader2 className="animate-spin" aria-hidden />}
          {checking ? busyAction : action}
        </Button>
        <span className="text-xs text-subtle-foreground" role="status" aria-live="polite">
          {checking ? (
            <>
              {busyTiming} <ElapsedTime />
            </>
          ) : (
            timing
          )}
        </span>
      </div>
      {checking && (
        <div aria-hidden className="mt-5 h-1 overflow-hidden rounded-full bg-raised">
          <div className="h-full w-1/3 animate-scan rounded-full bg-iris/70" />
        </div>
      )}
      {error && (
        <p role="alert" className="mt-4 text-sm text-rose">
          {error}
        </p>
      )}
    </section>
  );
}

export function LoadingBlocks() {
  return (
    <div className="flex flex-col gap-4" aria-busy="true">
      <span className="sr-only">Loading</span>
      <div className="h-44 w-full animate-pulse rounded-xl bg-raised" />
      <div className="h-64 w-full animate-pulse rounded-xl bg-raised" />
    </div>
  );
}

export function LoadError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-3 py-16 text-center">
      <p className="text-sm text-muted-foreground">{message}</p>
      <Button size="sm" onClick={onRetry}>
        Try again
      </Button>
    </div>
  );
}

/** Counted filter chips ("All 49", "To review 9"). */
export function FilterChips<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { id: T; label: string; count: number }[];
  value: T;
  onChange: (id: T) => void;
}) {
  return (
    <div role="group" aria-label={label} className="mt-6 flex flex-wrap gap-2">
      {options.map((option) => {
        const active = value === option.id;
        return (
          <button
            key={option.id}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(option.id)}
            className={cn(
              "h-8 rounded-full border px-3.5 text-[13px] transition-colors",
              active
                ? "border-border-strong bg-raised text-heading"
                : "border-border text-muted-foreground hover:border-border-strong hover:text-heading"
            )}
          >
            {option.label} <span className="figures ml-1">{option.count}</span>
          </button>
        );
      })}
    </div>
  );
}
