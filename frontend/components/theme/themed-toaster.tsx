"use client";

import { useSyncExternalStore } from "react";
import { Toaster } from "sonner";
import { getTheme, onThemeChange, type Theme } from "@/lib/theme";

export function ThemedToaster() {
  const theme = useSyncExternalStore(onThemeChange, getTheme, () => "dark" as Theme);
  return (
    <Toaster
      theme={theme}
      position="top-center"
      toastOptions={{
        classNames: {
          toast: "!bg-raised !border-border !text-foreground",
          description: "!text-muted-foreground",
        },
      }}
    />
  );
}
