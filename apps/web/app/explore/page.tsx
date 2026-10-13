import { apiFetch, NicheOut } from "@/lib/api";
import { ExploreClient } from "./ExploreClient";

export default async function ExplorePage() {
  let niches: NicheOut[] = [];
  let watchlistIds: string[] = [];
  let error: string | null = null;

  try {
    [niches, watchlistIds] = await Promise.all([
      apiFetch<NicheOut[]>("/api/v1/niches?limit=200"),
      apiFetch<NicheOut[]>("/api/v1/watchlist").then((items) =>
        items.map((i) => i.id)
      ),
    ]);
  } catch (e) {
    error = e instanceof Error ? e.message : "unknown error";
  }

  if (error) {
    return (
      <main style={{ padding: "40px 24px", color: "var(--muted)", fontSize: 13 }}>
        <p>
          Could not load niches from the API ({error}). Make sure the API is
          running and <code>NEXT_PUBLIC_API_URL</code> is set.
        </p>
      </main>
    );
  }

  return (
    <ExploreClient
      initialNiches={niches}
      watchlistIds={new Set(watchlistIds)}
    />
  );
}
