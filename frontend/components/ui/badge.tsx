import type { HTMLAttributes } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs leading-5",
  {
    variants: {
      tone: {
        neutral: "border border-border-strong text-muted-foreground",
        iris: "bg-iris/15 text-iris-strong",
        sage: "bg-sage/12 text-sage",
        honey: "bg-honey/12 text-honey",
        rose: "bg-rose/12 text-rose",
        slate: "bg-slate/12 text-slate",
      },
    },
    defaultVariants: { tone: "neutral" },
  }
);

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}

export { badgeVariants };
