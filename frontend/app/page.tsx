"use client";

import { useRouter } from "next/navigation";
import { toast } from "sonner";
import FileUpload from "@/components/upload/file-upload";
import type { UploadResponse } from "@/lib/api";

export default function Home() {
  const router = useRouter();

  function handleUploadSuccess(_file: File, response: UploadResponse) {
    if (response.status === "empty_text") {
      toast.error(
        response.message ??
          "Couldn't read text from this file — it may be a scanned/image-only document."
      );
      return;
    }
    if (response.status === "parse_failed") {
      toast.error("This file couldn't be read. It may be corrupted.");
      return;
    }
    if (response.reused_existing) {
      toast.info("This paper was already uploaded — resuming your session.");
    }
    router.push(`/paper/${response.paper_id}`);
  }

  // Deliberately no onUploadError handler here — the upload card already
  // renders its own inline error state (and auto-clears it after 3s), so
  // adding a toast on top of it doubled up the same message on screen at
  // once, confirmed while testing the real upload flow end-to-end.

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-8 bg-background px-6 text-foreground">
      <div className="text-center">
        <h1 className="text-4xl font-semibold tracking-tight">ReSense</h1>
        <p className="mt-2 text-muted-foreground">
          Upload a research paper to get tone-adaptive summaries, grounded Q&amp;A, and visual analysis.
        </p>
      </div>
      <FileUpload onUploadSuccess={handleUploadSuccess} />
    </main>
  );
}