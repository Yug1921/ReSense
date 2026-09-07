"use client";

import { useEffect, useState } from "react";
import { motion } from "motion/react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  ResponsiveContainer,
  Tooltip,
  Cell,
} from "recharts";
import { analyzePaper, ApiError, type AnalyzeResponse } from "@/lib/api";

function truncateLabel(label: string, maxLength = 22): string {
  return label.length > maxLength ? label.slice(0, maxLength - 1) + "…" : label;
}

function YAxisTick({
  x,
  y,
  payload,
}: {
  x?: number;
  y?: number;
  payload?: { value?: string };
}) {
  const label = String(payload?.value ?? "");

  return (
    <g transform={`translate(${x ?? 0},${y ?? 0})`}>
      <title>{label}</title>
      <text x={-8} dy="0.32em" textAnchor="end" fill="#a1a1aa" fontSize={11}>
        {truncateLabel(label)}
      </text>
    </g>
  );
}

export interface AnalysisPanelProps {
  paperId: string;
  className?: string;
}

type Phase = "loading" | "ready" | "error";

const RING_COLORS = {
  complexity: "#fb2c36",
  structure: "#2cb0fb",
  focus: "#2cfb8f",
};

const CANONICAL_SECTIONS = [
  "abstract",
  "introduction",
  "method",
  "methodology",
  "results",
  "discussion",
  "conclusion",
];

function computeStructureScore(sectionLengths: AnalyzeResponse["section_lengths"]): number {
  const found = new Set(
    sectionLengths
      .map((s) => s.label.toLowerCase())
      .filter((label) => CANONICAL_SECTIONS.some((c) => label.includes(c)))
  );
  const distinctSlots = new Set(
    [...found].map((f) => (f.includes("method") ? "method" : f))
  );
  return Math.min(100, Math.round((distinctSlots.size / 5) * 100));
}

function computeFocusScore(keywords: AnalyzeResponse["keywords"]): number {
  if (keywords.length === 0) return 0;
  const total = keywords.reduce((sum, k) => sum + k.value, 0);
  if (total === 0) return 0;
  const topShare = keywords[0].value / total;
  return Math.min(100, Math.round(topShare * 300));
}

function Ring({
  label,
  value,
  color,
  size = 120,
  strokeWidth = 12,
  delay = 0,
}: {
  label: string;
  value: number;
  color: string;
  size?: number;
  strokeWidth?: number;
  delay?: number;
}) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="-rotate-90">
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="rgba(255,255,255,0.08)"
            strokeWidth={strokeWidth}
          />
          <motion.circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeDasharray={circumference}
            initial={{ strokeDashoffset: circumference }}
            animate={{ strokeDashoffset: circumference * (1 - value / 100) }}
            transition={{ duration: 1, delay, ease: "easeOut" }}
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center text-lg font-semibold text-white">
          {value}
        </div>
      </div>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  );
}

export function AnalysisPanel({ paperId, className }: AnalysisPanelProps) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [data, setData] = useState<AnalyzeResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setPhase("loading");

    analyzePaper(paperId)
      .then((res) => {
        if (cancelled) return;
        setData(res);
        setPhase("ready");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message = err instanceof ApiError ? err.message : "Couldn't load analysis for this paper.";
        setErrorMessage(message);
        setPhase("error");
      });

    return () => {
      cancelled = true;
    };
  }, [paperId]);

  if (phase === "loading") {
    return (
      <div className={className}>
        <p className="text-sm text-muted-foreground">Analyzing paper structure…</p>
      </div>
    );
  }

  if (phase === "error" || !data) {
    return (
      <div className={className}>
        <p className="text-sm text-red-400">{errorMessage}</p>
      </div>
    );
  }

  const complexityScore = data.classification ? data.classification.complexity_score * 10 : 0;
  const structureScore = computeStructureScore(data.section_lengths);
  const focusScore = computeFocusScore(data.keywords);

  return (
    <div className={className}>
      <div className="flex flex-wrap justify-center gap-8 rounded-xl border border-white/10 bg-white/[0.02] p-6">
        <Ring label="Complexity" value={complexityScore} color={RING_COLORS.complexity} delay={0} />
        <Ring label="Structure" value={structureScore} color={RING_COLORS.structure} delay={0.15} />
        <Ring label="Keyword Focus" value={focusScore} color={RING_COLORS.focus} delay={0.3} />
      </div>

      {data.classification && (
        <p className="mt-4 text-center text-sm text-muted-foreground">
          Detected as a{" "}
          <span className="text-zinc-200">{data.classification.paper_type.replace("_", " ")}</span> paper,{" "}
          {data.classification.complexity} complexity.
        </p>
      )}

      <div className="mt-8 grid gap-6 sm:grid-cols-2">
        <div className="rounded-xl border border-white/10 bg-white/[0.02] p-4">
          <h3 className="mb-3 text-sm font-medium text-zinc-300">Section Length</h3>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={data.section_lengths} layout="vertical" margin={{ left: 16, right: 16 }}>
              <XAxis type="number" hide />
              <YAxis
                type="category"
                dataKey="label"
                width={150}
                tickFormatter={(label: string) => truncateLabel(label)}
                axisLine={false}
                tickLine={false}
                interval={0}
                tick={<YAxisTick />}
              />
              <Tooltip
                contentStyle={{ background: "#18181b", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8 }}
                labelStyle={{ color: "#e4e4e7" }}
              />
              <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                {data.section_lengths.map((_, i) => (
                  <Cell key={i} fill={RING_COLORS.structure} fillOpacity={0.8} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="rounded-xl border border-white/10 bg-white/[0.02] p-4">
          <h3 className="mb-3 text-sm font-medium text-zinc-300">Top Keywords</h3>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={data.keywords.slice(0, 8)} layout="vertical" margin={{ left: 16, right: 16 }}>
              <XAxis type="number" hide />
              <YAxis
                type="category"
                dataKey="label"
                width={150}
                tickFormatter={(label: string) => truncateLabel(label)}
                axisLine={false}
                tickLine={false}
                interval={0}
                tick={<YAxisTick />}
              />
              <Tooltip
                contentStyle={{ background: "#18181b", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8 }}
                labelStyle={{ color: "#e4e4e7" }}
              />
              <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                {data.keywords.slice(0, 8).map((_, i) => (
                  <Cell key={i} fill={RING_COLORS.focus} fillOpacity={0.8} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}

export default AnalysisPanel;