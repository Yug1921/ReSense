"use client";

import { Suspense } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import type { UploadResponse } from "@/lib/api";
import { RequireAuth } from "@/components/auth/require-auth";
import { AccountMenu } from "@/components/auth/account-menu";
import { AiPicker } from "@/components/ai/ai-picker";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { Logo } from "@/components/brand/logo";
import { UploadCard } from "@/components/upload/upload-card";
import { PapersList } from "@/components/home/papers-list";

const STEPS = [
  { title: "Upload", text: "We read the text and its sections" },
  { title: "Read it your way", text: "Summaries in five tones, and answers" },
  { title: "Check references", text: "Matched against Crossref, OpenAlex and arXiv" },
];

function Home() {
  const router = useRouter();

  function handleUploaded(response: UploadResponse) {
    if (response.reused_existing) toast("You've uploaded this paper before. Opening it.");
    router.push(`/paper/${response.paper_id}`);
  }

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-divider">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-10">
          <Logo />
          <div className="flex items-center gap-3">
            <AiPicker />
            <ThemeToggle />
            <AccountMenu />
          </div>
        </div>
      </header>

      <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col items-center px-4 pb-16 pt-14 sm:pt-20">
        <h1 className="text-center text-3xl font-semibold leading-tight tracking-tight sm:text-[40px]">
          Understand any research paper
        </h1>
        <p className="mt-3.5 max-w-md text-center text-base leading-relaxed text-muted-foreground sm:text-[17px]">
          Upload a paper to read it in the tone you need, ask it questions, and check its references.
        </p>

        <div className="mt-10 w-full max-w-xl">
          <UploadCard onUploaded={handleUploaded} />
        </div>

        <ol className="mt-9 grid w-full max-w-xl grid-cols-1 gap-4 sm:grid-cols-3">
          {STEPS.map((step, index) => (
            <li key={step.title} className="flex items-start gap-2.5">
              <span className="figures pt-0.5 text-xs text-iris">{String(index + 1).padStart(2, "0")}</span>
              <div>
                <p className="text-sm font-medium text-foreground">{step.title}</p>
                <p className="text-[13px] leading-normal text-subtle-foreground">{step.text}</p>
              </div>
            </li>
          ))}
        </ol>

        <div className="mt-12 w-full max-w-xl">
          <PapersList />
        </div>
      </main>
    </div>
  );
}

export default function HomePage() {
  return (
    <Suspense>
      <RequireAuth>
        <Home />
      </RequireAuth>
    </Suspense>
  );
}
