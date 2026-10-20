"use client";

import { useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface PaperTab {
  id: string;
  label: string;
  content: ReactNode;
}

// Inactive tabs stay mounted (just hidden) so switching back keeps their state.
export function PaperTabs({ tabs }: { tabs: PaperTab[] }) {
  const [activeId, setActiveId] = useState(tabs[0]?.id);

  return (
    <div className="flex w-full flex-col items-center gap-10">
      <div role="tablist" className="inline-flex rounded-lg border border-white/10 bg-white/[0.02] p-1">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            id={`tab-${tab.id}`}
            aria-selected={tab.id === activeId}
            aria-controls={`panel-${tab.id}`}
            onClick={() => setActiveId(tab.id)}
            className={cn(
              "rounded-md px-4 py-1.5 text-sm transition-colors",
              tab.id === activeId ? "bg-white/10 text-white" : "text-zinc-400 hover:text-zinc-200"
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {tabs.map((tab) => (
        <div
          key={tab.id}
          role="tabpanel"
          id={`panel-${tab.id}`}
          aria-labelledby={`tab-${tab.id}`}
          hidden={tab.id !== activeId}
          className="w-full"
        >
          {tab.content}
        </div>
      ))}
    </div>
  );
}

export default PaperTabs;
