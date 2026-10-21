"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import { getSupabase } from "@/lib/supabase";
import { Button } from "@/components/ui/button";
import { Logo } from "@/components/brand/logo";
import { useAuth } from "./auth-provider";

type Mode = "sign-in" | "sign-up";

const MIN_PASSWORD = 8;

// Only send people back to pages inside this app.
function safeNext(value: string | null) {
  return value && value.startsWith("/") && !value.startsWith("//") ? value : "/";
}

function friendlyError(message: string) {
  const text = message.toLowerCase();
  if (text.includes("invalid login")) return "That email and password don't match. Check them and try again.";
  if (text.includes("already registered")) return "An account with this email already exists. Sign in instead.";
  if (text.includes("email not confirmed")) return "Confirm your email first. Check your inbox for the link we sent.";
  if (text.includes("rate limit") || text.includes("too many")) return "Too many attempts. Wait a minute and try again.";
  if (text.includes("fetch")) return "We couldn't reach the sign-in service. Check your connection.";
  return message;
}

export function SignInForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const next = safeNext(searchParams.get("next"));
  const { session, loading, configured } = useAuth();

  const [mode, setMode] = useState<Mode>("sign-in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && session) router.replace(next);
  }, [loading, session, next, router]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    if (mode === "sign-up" && password.length < MIN_PASSWORD) {
      setError(`Use at least ${MIN_PASSWORD} characters for your password.`);
      return;
    }
    setBusy(true);
    try {
      const auth = getSupabase().auth;
      if (mode === "sign-in") {
        const { error: signInError } = await auth.signInWithPassword({ email, password });
        if (signInError) throw signInError;
      } else {
        const { data, error: signUpError } = await auth.signUp({ email, password });
        if (signUpError) throw signUpError;
        if (!data.session) {
          setNotice(`We sent a confirmation link to ${email}. Open it, then sign in here.`);
          setMode("sign-in");
          setPassword("");
        }
      }
    } catch (err: unknown) {
      setError(friendlyError(err instanceof Error ? err.message : "Something went wrong. Try again."));
    } finally {
      setBusy(false);
    }
  }

  const isSignIn = mode === "sign-in";

  return (
    <main className="flex min-h-screen flex-col items-center justify-center px-4 py-12">
      <Logo />
      <div className="mt-8 w-full max-w-sm rounded-xl border border-border bg-card p-6 sm:p-8">
        <h1 className="text-xl font-semibold tracking-tight">{isSignIn ? "Sign in" : "Create your account"}</h1>
        <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
          {isSignIn
            ? "Your papers, summaries and checks are saved to your account."
            : "Keep every paper you upload in one place. You stay signed in on this device."}
        </p>

        {!configured ? (
          <p className="mt-6 rounded-lg border border-honey/30 bg-honey/10 px-3 py-2.5 text-sm text-honey">
            Sign-in is not set up yet. Add the Supabase URL and anon key to frontend/.env.local.
          </p>
        ) : (
          <form onSubmit={handleSubmit} className="mt-6 flex flex-col gap-4" noValidate>
            <label className="flex flex-col gap-1.5">
              <span className="text-[13px] font-medium text-foreground">Email</span>
              <input
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                className="h-10 rounded-lg border border-border bg-background px-3 text-sm text-heading outline-none transition-colors placeholder:text-subtle-foreground focus:border-iris"
                placeholder="you@university.edu"
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-[13px] font-medium text-foreground">Password</span>
              <input
                type="password"
                autoComplete={isSignIn ? "current-password" : "new-password"}
                required
                minLength={isSignIn ? undefined : MIN_PASSWORD}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="h-10 rounded-lg border border-border bg-background px-3 text-sm text-heading outline-none transition-colors focus:border-iris"
              />
              {!isSignIn && <span className="text-xs text-subtle-foreground">At least {MIN_PASSWORD} characters.</span>}
            </label>

            {error && (
              <p role="alert" className="text-sm leading-relaxed text-rose">
                {error}
              </p>
            )}
            {notice && (
              <p role="status" className="text-sm leading-relaxed text-sage">
                {notice}
              </p>
            )}

            <Button type="submit" variant="primary" disabled={busy || !email || !password} className="mt-1 w-full">
              {busy && <Loader2 className="animate-spin" aria-hidden />}
              {isSignIn ? "Sign in" : "Create account"}
            </Button>
          </form>
        )}
      </div>

      {configured && (
        <p className="mt-6 text-sm text-muted-foreground">
          {isSignIn ? "New to ReSense?" : "Already have an account?"}{" "}
          <button
            type="button"
            onClick={() => {
              setMode(isSignIn ? "sign-up" : "sign-in");
              setError(null);
              setNotice(null);
            }}
            className="text-iris hover:text-iris-strong"
          >
            {isSignIn ? "Create an account" : "Sign in"}
          </button>
        </p>
      )}
    </main>
  );
}
