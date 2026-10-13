import { apiFetch } from "@/lib/api";
import { NextRequest, NextResponse } from "next/server";

export async function DELETE(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  await apiFetch(`/api/v1/watchlist/${id}`);
  return new NextResponse(null, { status: 204 });
}
