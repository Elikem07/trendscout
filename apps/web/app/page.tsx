import Link from "next/link";
import { SignInButton, UserButton } from "@clerk/nextjs";
import { auth } from "@clerk/nextjs/server";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Health = { status: string; version: string; environment: string };

async function getApiHealth(): Promise<Health | null> {
  try {
    const res = await fetch(`${API_URL}/health`, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as Health;
  } catch {
    return null;
  }
}

export default async function Home() {
  const [health, { userId }] = await Promise.all([getApiHealth(), auth()]);

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center gap-8 px-6">
      <div>
        <p className="text-sm tracking-widest uppercase" style={{ color: "var(--muted)" }}>
          M0.T1 scaffold
        </p>
        <h1 className="mt-2 text-4xl font-semibold tracking-tight">TrendScout</h1>
        <p className="mt-3 max-w-md" style={{ color: "var(--muted)" }}>
          Find demand before it becomes competition.
        </p>
      </div>

      <div className="flex items-center gap-4 text-sm">
        {userId ? (
          <>
            <Link href="/dashboard" className="underline underline-offset-4">
              Open dashboard
            </Link>
            <UserButton />
          </>
        ) : (
          <SignInButton mode="modal">
            <button
              className="rounded-md px-4 py-2 font-medium"
              style={{ background: "var(--accent)", color: "#fff" }}
            >
              Sign in
            </button>
          </SignInButton>
        )}
      </div>

      <div
        className="rounded-lg border p-4 text-sm"
        style={{ borderColor: "var(--border)" }}
      >
        <div className="flex items-center gap-2">
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{ background: health ? "#3fb950" : "#f85149" }}
          />
          <span>API {health ? "connected" : "unreachable"}</span>
        </div>
        <dl className="mt-3 grid grid-cols-2 gap-1" style={{ color: "var(--muted)" }}>
          <dt>Endpoint</dt>
          <dd className="text-right font-mono">{API_URL}</dd>
          <dt>Version</dt>
          <dd className="text-right font-mono">{health?.version ?? "n/a"}</dd>
          <dt>Environment</dt>
          <dd className="text-right font-mono">{health?.environment ?? "n/a"}</dd>
        </dl>
      </div>
    </main>
  );
}
