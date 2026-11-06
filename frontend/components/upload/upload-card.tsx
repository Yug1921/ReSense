"use client";

import { useRef, useState, type DragEvent } from "react";
import { FileUp, Loader2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { ApiError, uploadPaper, type UploadResponse } from "@/lib/api";
import { Button } from "@/components/ui/button";

const MAX_MB = 20; // matches the backend's MAX_UPLOAD_MB
const ACCEPTED = [".pdf", ".docx", ".doc"];

type State =
  | { kind: "idle" }
  | { kind: "uploading"; name: string; percent: number }
  | { kind: "reading"; name: string }
  | { kind: "error"; message: string };

function checkFile(file: File): string | null {
  const name = file.name.toLowerCase();
  if (!ACCEPTED.some((ext) => name.endsWith(ext))) return "That file type isn't supported. Choose a PDF or Word document.";
  if (file.size === 0) return "That file is empty. Choose another one.";
  if (file.size > MAX_MB * 1024 * 1024) return `That file is larger than ${MAX_MB} MB. Choose a smaller one.`;
  return null;
}

// Upload states are real: the bar follows bytes sent, then we wait for the
// server to read the paper. Nothing is animated for show.
export function UploadCard({ onUploaded }: { onUploaded: (response: UploadResponse) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<(() => void) | null>(null);
  const [state, setState] = useState<State>({ kind: "idle" });
  const [dragging, setDragging] = useState(false);

  const busy = state.kind === "uploading" || state.kind === "reading";

  function start(file: File) {
    const problem = checkFile(file);
    if (problem) {
      setState({ kind: "error", message: problem });
      return;
    }
    setState({ kind: "uploading", name: file.name, percent: 0 });
    const { promise, abort } = uploadPaper(file, (percent) => {
      setState(percent >= 100 ? { kind: "reading", name: file.name } : { kind: "uploading", name: file.name, percent });
    });
    abortRef.current = abort;
    promise
      .then((response) => {
        if (response.status === "empty_text") {
          setState({
            kind: "error",
            message: "We couldn't find any text in this file. It may be a scanned image. Try a text-based PDF.",
          });
          return;
        }
        onUploaded(response);
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.message === "Upload cancelled.") {
          setState({ kind: "idle" });
          return;
        }
        if (err instanceof ApiError && err.status === 401) return; // being sent to sign in
        const message =
          err instanceof ApiError && err.status === 422
            ? "This file couldn't be read. It may be damaged. Try exporting it again."
            : err instanceof ApiError && err.status === 0
              ? "We couldn't reach ReSense. Check your connection and try again."
              : err instanceof ApiError
                ? err.message
                : "Something went wrong. Try again.";
        setState({ kind: "error", message });
      })
      .finally(() => {
        abortRef.current = null;
        if (inputRef.current) inputRef.current.value = "";
      });
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    if (busy) return;
    const file = event.dataTransfer.files?.[0];
    if (file) start(file);
  }

  return (
    <div className="w-full rounded-2xl border border-border bg-card p-2">
      <div
        onDragOver={(event) => {
          event.preventDefault();
          if (!busy) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        className={cn(
          "flex min-h-60 flex-col items-center justify-center gap-3 rounded-xl border-[1.5px] border-dashed px-6 py-10 text-center transition-colors",
          dragging ? "border-iris bg-iris/5" : "border-border-strong"
        )}
      >
        {busy ? (
          <div className="flex w-full max-w-xs flex-col items-center gap-3" role="status" aria-live="polite">
            <Loader2 className="size-5 animate-spin text-iris" aria-hidden />
            <p className="max-w-full truncate text-sm font-medium text-heading">{state.name}</p>
            {state.kind === "uploading" ? (
              <>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-raised">
                  <div className="h-full rounded-full bg-iris transition-[width]" style={{ width: `${state.percent}%` }} />
                </div>
                <p className="text-[13px] text-muted-foreground">
                  Uploading <span className="figures">{state.percent}%</span>
                </p>
              </>
            ) : (
              <p className="text-[13px] text-muted-foreground">Reading the text and sections. Long papers take a little longer.</p>
            )}
            {state.kind === "uploading" && (
              <Button variant="ghost" size="sm" onClick={() => abortRef.current?.()}>
                Cancel
              </Button>
            )}
          </div>
        ) : (
          <>
            <div className="flex size-12 items-center justify-center rounded-xl bg-iris/12">
              <FileUp className="size-[22px] text-iris" aria-hidden />
            </div>
            <p className="text-base font-medium text-heading">Drop your paper here</p>
            <p className="text-[13px] text-subtle-foreground">PDF or Word document, up to {MAX_MB} MB</p>
            <Button variant="primary" className="mt-1.5" onClick={() => inputRef.current?.click()}>
              Choose a file
            </Button>
          </>
        )}
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED.join(",")}
          className="sr-only"
          tabIndex={-1}
          aria-hidden
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) start(file);
          }}
        />
      </div>
      {state.kind === "error" && (
        <div role="alert" className="mt-2 flex items-start gap-3 rounded-lg bg-rose/10 px-3.5 py-2.5 text-sm text-rose">
          <p className="flex-1 leading-relaxed">{state.message}</p>
          <button
            type="button"
            aria-label="Dismiss"
            onClick={() => setState({ kind: "idle" })}
            className="mt-0.5 text-rose/80 hover:text-rose"
          >
            <X className="size-4" aria-hidden />
          </button>
        </div>
      )}
    </div>
  );
}
