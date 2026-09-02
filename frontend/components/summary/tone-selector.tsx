"use client";

import { motion, AnimatePresence } from "motion/react";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";
import { TONES, type Tone } from "@/lib/api";

const springTransition = {
  type: "spring" as const,
  stiffness: 500,
  damping: 30,
  mass: 0.5,
};

export interface ToneSelectorProps {
  value: Tone | null;
  onChange: (tone: Tone) => void;
  disabled?: boolean;
  className?: string;
}

/**
 * Adapted from the cuisine-selector-chips template: same spring-physics
 * chip animation and checkmark badge, but single-select (a radio group,
 * not a multi-select toggle list) since a summary is generated in exactly
 * one tone at a time.
 */
export function ToneSelector({ value, onChange, disabled, className }: ToneSelectorProps) {
  return (
    <div className={cn("w-full", className)}>
      <motion.div
        role="radiogroup"
        aria-label="Summary tone"
        className="flex flex-wrap justify-center gap-3"
        layout
        transition={springTransition}
      >
        {TONES.map((tone) => {
          const isSelected = value === tone.id;
          return (
            <motion.button
              key={tone.id}
              type="button"
              role="radio"
              aria-checked={isSelected}
              disabled={disabled}
              onClick={() => onChange(tone.id)}
              layout
              initial={false}
              animate={{
                backgroundColor: isSelected ? "rgba(59,130,246,0.14)" : "rgba(39,39,42,0.5)",
              }}
              whileHover={
                disabled ? undefined : { backgroundColor: isSelected ? "rgba(59,130,246,0.18)" : "rgba(39,39,42,0.8)" }
              }
              whileTap={disabled ? undefined : { scale: 0.97 }}
              transition={{ ...springTransition, backgroundColor: { duration: 0.1 } }}
              className={cn(
                "inline-flex items-center whitespace-nowrap overflow-hidden rounded-full px-4 py-2 text-sm font-medium ring-1 ring-inset transition-opacity",
                isSelected ? "text-blue-300 ring-blue-500/30" : "text-zinc-400 ring-white/[0.06]",
                disabled && "cursor-not-allowed opacity-50"
              )}
            >
              <motion.div
                className="relative flex items-center"
                animate={{ paddingRight: isSelected ? "1.5rem" : "0" }}
                transition={{ ease: [0.175, 0.885, 0.32, 1.275], duration: 0.3 }}
              >
                <span>{tone.label}</span>
                <AnimatePresence>
                  {isSelected && (
                    <motion.span
                      initial={{ scale: 0, opacity: 0 }}
                      animate={{ scale: 1, opacity: 1 }}
                      exit={{ scale: 0, opacity: 0 }}
                      transition={springTransition}
                      className="absolute right-0"
                    >
                      <div className="flex h-4 w-4 items-center justify-center rounded-full bg-blue-400">
                        <Check className="h-3 w-3 text-blue-950" strokeWidth={2} />
                      </div>
                    </motion.span>
                  )}
                </AnimatePresence>
              </motion.div>
            </motion.button>
          );
        })}
      </motion.div>

      <AnimatePresence mode="wait">
        {value && (
          <motion.p
            key={value}
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.15 }}
            className="mt-3 text-center text-xs text-muted-foreground"
          >
            {TONES.find((t) => t.id === value)?.description}
          </motion.p>
        )}
      </AnimatePresence>
    </div>
  );
}

export default ToneSelector;