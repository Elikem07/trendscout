import { apiFetch, NicheDetailOut } from "@/lib/api";
import { NextRequest, NextResponse } from "next/server";

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ slug: string }> }
) {
  const { slug } = await params;
  const detail = await apiFetch<NicheDetailOut>(`/api/v1/niches/${slug}`);
  return NextResponse.json(detail);
}
