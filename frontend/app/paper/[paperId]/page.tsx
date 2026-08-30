export default async function PaperPage({
  params,
}: {
  params: Promise<{ paperId: string }>;
}) {
  const { paperId } = await params;
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 bg-background px-6 text-foreground">
      <h1 className="text-2xl font-semibold">Paper workspace</h1>
      <p className="text-muted-foreground">
        paper_id: <code className="rounded bg-muted px-2 py-1 font-mono text-sm">{paperId}</code>
      </p>
      <p className="max-w-md text-center text-sm text-muted-foreground">
        Summary, analysis, and Q&amp;A panels land here in Parts 3–5.
      </p>
    </main>
  );
}