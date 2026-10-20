export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export type PaperStatus = "uploaded" | "parsing" | "ready" | "parse_failed" | "empty_text";

export interface UploadResponse {
  paper_id: string;
  status: PaperStatus;
  filename: string;
  structure: Record<string, unknown>;
  message?: string | null;
  reused_existing: boolean;
}

export type Tone =
  | "academic"
  | "technical"
  | "research_insight"
  | "figure_table_analysis"
  | "critical_review";

export interface ToneMeta {
  id: Tone;
  label: string;
  description: string;
}

export const TONES: ToneMeta[] = [
  { id: "academic", label: "Academic", description: "Follows the paper's own structure and preserves its terminology." },
  { id: "technical", label: "Technical", description: "Algorithms, architecture, dataset, parameters, evaluation metrics." },
  { id: "research_insight", label: "Research Insight", description: "Problem, gap, novelty, contribution, significance." },
  { id: "figure_table_analysis", label: "Figure & Table Analysis", description: "What each figure/table shows and what it supports." },
  { id: "critical_review", label: "Critical Review", description: "What's demonstrated vs. merely claimed; limitations." },
];

export interface SummarizeResponse {
  paper_id: string;
  tone: Tone;
  content: string;
  cached: boolean;
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  let data: unknown;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  if (!res.ok) {
    const detail = (data as { detail?: string } | null)?.detail ?? `Request failed (${res.status})`;
    throw new ApiError(detail, res.status);
  }
  return data as T;
}

export interface ChartPoint {
  label: string;
  value: number;
}

export interface Classification {
  paper_type: string;
  complexity: string;
  complexity_score: number;
}

export interface AnalyzeResponse {
  paper_id: string;
  section_lengths: ChartPoint[];
  keywords: ChartPoint[];
  structure_score: number;
  classification: Classification | null;
  cached: boolean;
}

export interface AskResponse {
  paper_id: string;
  answer: string;
  used_sections: string[];
}

export function askPaper(paperId: string, question: string): Promise<AskResponse> {
  return postJson<AskResponse>("/ask", { paper_id: paperId, question });
}

export function analyzePaper(paperId: string): Promise<AnalyzeResponse> {
  return postJson<AnalyzeResponse>("/analyze", { paper_id: paperId });
}

export function summarizePaper(
  paperId: string,
  tone: Tone,
  refresh = false
): Promise<SummarizeResponse> {
  return postJson<SummarizeResponse>("/summarize", { paper_id: paperId, tone, refresh });
}

export function uploadPaper(
  file: File,
  onProgress?: (percent: number) => void
): { promise: Promise<UploadResponse>; abort: () => void } {
  const xhr = new XMLHttpRequest();
  const formData = new FormData();
  formData.append("file", file);

  const promise = new Promise<UploadResponse>((resolve, reject) => {
    xhr.open("POST", `${API_BASE_URL}/upload`);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };
    xhr.onload = () => {
      let body: unknown;
      try { body = JSON.parse(xhr.responseText); } catch { body = null; }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as UploadResponse);
      } else {
        const detail = (body as { detail?: string } | null)?.detail ?? "Upload failed.";
        reject(new ApiError(detail, xhr.status));
      }
    };
    xhr.onerror = () => reject(new ApiError("Network error — is the backend running?", 0));
    xhr.onabort = () => reject(new ApiError("Upload cancelled.", 0));
    xhr.send(formData);
  });

  return { promise, abort: () => xhr.abort() };
}

export type ReferenceStatus = "verified" | "uncertain" | "not_found" | "unavailable";

export type PublicationRelation = "exact" | "same_work_version" | "possible_related" | "different_work";

export interface ReferenceItem {
  index: number;
  raw: string;
  status: ReferenceStatus;
  similarity: number;
  matched_title: string | null;
  matched_doi: string | null;
  matched_year: number | null;
  error: string | null;
  source: string | null;
  publication_relation: PublicationRelation | null;
  match_reason: string | null;
  conflict_fields: string[];
}

export interface ReferenceCheckResponse {
  paper_id: string;
  total: number;
  verified: number;
  uncertain: number;
  not_found: number;
  unavailable: number;
  items: ReferenceItem[];
  cached: boolean;
}

export function checkReferences(paperId: string, force = false): Promise<ReferenceCheckResponse> {
  return postJson<ReferenceCheckResponse>("/integrity/references", { paper_id: paperId, force });
}
