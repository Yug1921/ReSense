import { SummaryPanel } from "@/components/summary/summary-panel";
import { AnalysisPanel } from "@/components/analysis/analysis-panel";
import { ChatPanel } from "@/components/qa/chat-panel";
import { IntegrityPanel } from "@/components/integrity/integrity-panel";
import { PaperTabs } from "@/components/paper/paper-tabs";

export default async function PaperPage({
  params,
}: {
  params: Promise<{ paperId: string }>;
}) {
  const { paperId } = await params;
  return (
    <main className="flex min-h-screen flex-col items-center gap-10 bg-background px-6 py-16 text-foreground">
      <h1 className="text-2xl font-semibold">Choose how you want this paper read</h1>
      <div className="w-full max-w-5xl">
        <PaperTabs
          tabs={[
            {
              id: "read",
              label: "Read",
              content: (
                <div className="flex w-full flex-col items-center gap-10">
                  <SummaryPanel paperId={paperId} />
                  <AnalysisPanel paperId={paperId} className="w-full" />
                  <ChatPanel paperId={paperId} />
                </div>
              ),
            },
            {
              id: "integrity",
              label: "Integrity Report",
              content: <IntegrityPanel paperId={paperId} />,
            },
          ]}
        />
      </div>
    </main>
  );
}
