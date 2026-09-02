import SummaryPanel from "@/components/summary/summary-panel";

export default async function PaperPage({
  params,
}: {
  params: Promise<{ paperId: string }>;
}) {
  const { paperId } = await params;
  return (
    <main className="flex min-h-screen flex-col items-center gap-10 bg-background px-6 py-16 text-foreground">
      <header className="text-center">
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
          Paper workspace
        </p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight">Make the paper legible.</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Choose how you want the summary to sound.
        </p>
      </header>

      <SummaryPanel paperId={paperId} className="max-w-3xl" />
    </main>
  );
}