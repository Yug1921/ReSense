import { Suspense } from "react";
import { PaperWorkspace } from "@/components/paper/paper-workspace";

export default async function PaperPage({
  params,
}: {
  params: Promise<{ paperId: string }>;
}) {
  const { paperId } = await params;
  return (
    <Suspense>
      <PaperWorkspace paperId={paperId} />
    </Suspense>
  );
}
