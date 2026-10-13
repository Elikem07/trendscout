import { apiFetch } from "@/lib/api";
import Link from "next/link";

type Me = { id: string; email: string; plan: string };

export default async function Dashboard() {
  let me: Me | null = null;
  try { me = await apiFetch<Me>("/me"); } catch {}

  return (
    <main style={{ maxWidth: 680, margin: "0 auto", padding: "48px 24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 32 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, letterSpacing: "-0.01em" }}>TrendScout</h1>
        {me && (
          <span style={{ color: "var(--muted)", fontSize: 13 }}>{me.email}</span>
        )}
      </div>

      <Link
        href="/explore"
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 4,
          padding: "20px 24px",
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: 8,
          textDecoration: "none",
          transition: "border-color 0.15s",
        }}
      >
        <span style={{ fontWeight: 600, fontSize: 15 }}>Explore niches →</span>
        <span style={{ color: "var(--muted)", fontSize: 13 }}>
          Browse emerging, hot, and trending product niches with scores, history, and revenue estimates.
        </span>
      </Link>

      {!me && (
        <p style={{ marginTop: 24, color: "var(--muted)", fontSize: 13 }}>
          API not reachable — start the API server and set{" "}
          <code style={{ fontFamily: "monospace" }}>NEXT_PUBLIC_API_URL</code>.
        </p>
      )}
    </main>
  );
}
