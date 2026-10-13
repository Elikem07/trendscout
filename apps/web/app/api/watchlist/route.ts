import { apiFetch } from "@/lib/api";
import { NextRequest, NextResponse } from "next/server";

export async function POST(req: NextRequest) {
  const body = await req.json() as { niche_id: string };
  const result = await apiFetch<{ status: string }>(`/api/v1/watchlist`);
  // proxy through to the backend with the body
  const { auth } = await import("@clerk/nextjs/server");
  const { getToken } = await auth();
  const token = await getToken();
  const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  const r = await fetch(`${API_URL}/api/v1/watchlist`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
