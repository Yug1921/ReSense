import { getAccessToken, getSupabase, isAuthConfigured } from "@/lib/supabase";
import { getAiChoice } from "@/lib/ai-choice";

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
  { id: "academic", label: "Academic", description: "Follows the paper's own structure" },
  { id: "technical", label: "Technical", description: "Methods, data, settings, metrics" },
  { id: "research_insight", label: "Research Insight", description: "Problem, what is new, why it matters" },
  { id: "figure_table_analysis", label: "Figures & Tables", description: "What each figure and table shows" },
  { id: "critical_review", label: "Critical Review", description: "Shown vs. claimed, limitations" },
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

async function authHeaders(): Promise<Record<string, string>> {
  const token = await getAccessToken();
  const headers: Record<string, string> = { "X-AI-Provider": getAiChoice() };
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

// The backend refused our sign-in (expired or revoked): sign out locally and
// send the person to sign in again, returning to this page afterwards.
function handleSignedOut() {
  if (typeof window === "undefined" || window.location.pathname.startsWith("/sign-in")) return;
  const next = `${window.location.pathname}${window.location.search}`;
  // A full page load (not router.push) so no signed-in state survives in memory.
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination
  const redirect = () => window.location.assign(`/sign-in?next=${encodeURIComponent(next)}`);
  if (isAuthConfigured()) getSupabase().auth.signOut().finally(redirect);
  else redirect();
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { ...(await authHeaders()), ...(init.headers as Record<string, string> | undefined) },
    });
  } catch {
    throw new ApiError("We couldn't reach ReSense. Check your connection and try again.", 0);
  }
  if (res.status === 401) handleSignedOut();
  if (res.status === 204) return undefined as T;
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

function postJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function getJson<T>(path: string): Promise<T> {
  return request<T>(path);
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
  reference_count?: number | null;
  cached: boolean;
}

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface PaperInfo {
  paper_id: string;
  filename: string;
  status: PaperStatus;
  structure: { word_count?: number; section_order?: string[] } & Record<string, unknown>;
}

export interface SessionResponse {
  paper: PaperInfo;
  summaries: Partial<Record<Tone, string>>;
  analysis: AnalyzeResponse | null;
  chat_history: ChatTurn[];
}

// Read-only: restores everything already generated for a paper, never starts new work.
export function getSession(paperId: string): Promise<SessionResponse> {
  return getJson<SessionResponse>(`/session/${encodeURIComponent(paperId)}`);
}

export interface PaperListItem {
  paper_id: string;
  filename: string;
  status: PaperStatus;
  uploaded_at: string;
  word_count: number | null;
}

// The signed-in person's papers, newest first.
export function listPapers(): Promise<PaperListItem[]> {
  return getJson<PaperListItem[]>("/papers");
}

export function deletePaper(paperId: string): Promise<void> {
  return request<void>(`/papers/${encodeURIComponent(paperId)}`, { method: "DELETE" });
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

  let aborted = false;

  const promise = authHeaders().then(
    (headers) =>
      new Promise<UploadResponse>((resolve, reject) => {
        if (aborted) {
          reject(new ApiError("Upload cancelled.", 0));
          return;
        }
        xhr.open("POST", `${API_BASE_URL}/upload`);
        for (const [name, value] of Object.entries(headers)) xhr.setRequestHeader(name, value);
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
            if (xhr.status === 401) handleSignedOut();
            const detail = (body as { detail?: string } | null)?.detail ?? "Upload failed.";
            reject(new ApiError(detail, xhr.status));
          }
        };
        xhr.onerror = () => reject(new ApiError("Network error — is the backend running?", 0));
        xhr.onabort = () => reject(new ApiError("Upload cancelled.", 0));
        xhr.send(formData);
      })
  );

  return {
    promise,
    abort: () => {
      aborted = true;
      xhr.abort();
    },
  };
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
  // The citation as written in the paper, split for display (best effort).
  cited_title: string | null;
  cited_authors: string | null;
  cited_venue: string | null;
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
  checked_at: string | null;
}

/** The last saved reference check, or null if this paper was never checked. */
export async function getSavedReferenceCheck(paperId: string): Promise<ReferenceCheckResponse | null> {
  const saved = await getJson<ReferenceCheckResponse | undefined>(
    `/integrity/references/${encodeURIComponent(paperId)}`
  );
  return saved ?? null;
}

export function checkReferences(paperId: string, force = false): Promise<ReferenceCheckResponse> {
  return postJson<ReferenceCheckResponse>("/integrity/references", { paper_id: paperId, force });
}
