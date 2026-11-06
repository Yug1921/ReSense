import { cn } from "@/lib/utils";

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-iris" aria-hidden>
        <path d="M5 4h9l5 5v11H5z" />
        <path d="M14 4v5h5" />
        <path d="M8.5 14.5l2 2 4-4.5" />
      </svg>
      <span className="text-[17px] font-semibold tracking-tight text-heading">ReSense</span>
    </span>
  );
}
