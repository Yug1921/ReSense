/**
 * Typed client for the ReSense FastAPI backend.
 *
 * Mirrors the Pydantic models in backend/app/models/schemas.py exactly —
 * keep these in sync if a backend response shape changes.
 */

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

export type Tone = "simple" | "technical" | "connect";

export const TONES: ReadonlyArray<{ id: Tone; label: string; description: string }> = [
  { id: "simple", label: "Simple", description: "A clear explanation without specialist jargon." },
  { id: "technical", label: "Technical", description: "Detailed language for a research-focused read." },
  { id: "connect", label: "Connect", description: "The main ideas linked to broader context and implications." },
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

export async function summarizePaper(
  paperId: string,
  tone: Tone
): Promise<SummarizeResponse> {
  const response = await fetch(`${API_BASE_URL}/summarize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paper_id: paperId, tone }),
  });

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (!response.ok) {
    const detail =
      (body as { detail?: string } | null)?.detail ??
      "Summary generation failed — the server didn't return a readable error.";
    throw new ApiError(detail, response.status);
  }

  return body as SummarizeResponse;
}

/**
 * Uploads a paper with real progress reporting via XMLHttpRequest — fetch()
 * has no upload-progress event, so XHR is the only way to drive an actual
 * (not simulated) progress bar for a multipart upload.
 */
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
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        body = null;
      }

      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as UploadResponse);
      } else {
        const detail =
          (body as { detail?: string } | null)?.detail ??
          "Upload failed — the server didn't return a readable error.";
        reject(new ApiError(detail, xhr.status));
      }
    };

    xhr.onerror = () => {
      reject(new ApiError("Network error — is the backend running?", 0));
    };
    xhr.onabort = () => {
      reject(new ApiError("Upload cancelled.", 0));
    };

    xhr.send(formData);
  });

  return { promise, abort: () => xhr.abort() };
}