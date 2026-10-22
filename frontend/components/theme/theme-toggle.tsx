"use client";

import { useSyncExternalStore } from "react";
import { Moon, Sun } from "lucide-react";
import { getTheme, onThemeChange, setTheme, type Theme } from "@/lib/theme";

/** Header button that switches between the dark and the soft light look. */
export function ThemeToggle() {
  const theme = useSyncExternalStore(onThemeChange, getTheme, () => "dark" as Theme);
  const next = theme === "dark" ? "light" : "dark";

  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      aria-label={`Switch to ${next} mode`}
      title={`Switch to ${next} mode`}
      className="relative inline-flex size-8 shrink-0 items-center justify-center overflow-hidden rounded-full border border-border text-muted-foreground transition-colors hover:border-border-strong hover:text-heading"
    >
      <Sun
        aria-hidden
        className={`absolute size-4 transition-all duration-300 ease-out ${
          theme === "light" ? "rotate-0 scale-100 opacity-100" : "-rotate-90 scale-50 opacity-0"
        }`}
      />
      <Moon
        aria-hidden
        className={`absolute size-4 transition-all duration-300 ease-out ${
          theme === "dark" ? "rotate-0 scale-100 opacity-100" : "rotate-90 scale-50 opacity-0"
        }`}
      />
    </button>
  );
}
