import { Suspense } from "react";
import { PaperWorkspace } from "@/components/paper/paper-workspace";
import { RequireAuth } from "@/components/auth/require-auth";

export default async function PaperPage({
  params,
}: {
  params: Promise<{ paperId: string }>;
}) {
  const { paperId } = await params;
  return (
    <Suspense>
      <RequireAuth>
        <PaperWorkspace paperId={paperId} />
      </RequireAuth>
    </Suspense>
  );
}
