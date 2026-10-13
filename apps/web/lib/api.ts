import { auth } from "@clerk/nextjs/server";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function apiFetch<T>(path: string): Promise<T> {
  const { getToken } = await auth();
  const token = await getToken();
  const res = await fetch(`${API_URL}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

export type TrendLabel = "emerging" | "rising" | "flat" | "declining" | "saturated";

export interface ScoreOut {
  date: string;
  demand: number;
  competition: number;
  opportunity: number;
  momentum: number;
  confidence: number;
  trend_label: TrendLabel;
  algo_version: string;
  subscores: Record<string, Record<string, number | null>>;
}

export interface NicheOut {
  id: string;
  label: string;
  slug: string;
  category: string | null;
  score: ScoreOut | null;
}

export interface NicheDetailOut extends NicheOut {
  history: ScoreOut[];
  revenue_low_usd: number | null;
  revenue_high_usd: number | null;
  active_listings: number;
}

export const LABEL_COLOR: Record<TrendLabel, string> = {
  emerging: "var(--emerging)",
  rising: "var(--rising)",
  flat: "var(--flat)",
  declining: "var(--declining)",
  saturated: "var(--saturated)",
};
