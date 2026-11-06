"use client";

import { useEffect, type ReactNode } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "./auth-provider";

// Shows its children only to signed-in people; everyone else goes to /sign-in
// and comes back to the same page afterwards.
export function RequireAuth({ children }: { children: ReactNode }) {
  const { session, loading, configured } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  useEffect(() => {
    if (loading || session) return;
    const query = searchParams.toString();
    const next = query ? `${pathname}?${query}` : pathname;
    router.replace(`/sign-in?next=${encodeURIComponent(next)}`);
  }, [loading, session, pathname, searchParams, router]);

  if (!configured) {
    return (
      <main className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center gap-2 px-6 text-center">
        <h1 className="text-xl font-semibold">Sign-in is not set up yet</h1>
        <p className="text-sm leading-relaxed text-muted-foreground">
          Add NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY to frontend/.env.local, then restart the app.
        </p>
      </main>
    );
  }

  if (loading || !session) {
    return <div className="min-h-screen" aria-busy="true" />;
  }

  return <>{children}</>;
}
