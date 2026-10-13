"use client";
import { useState, useMemo } from "react";
import { NicheOut, NicheDetailOut, TrendLabel, LABEL_COLOR } from "@/lib/api";
import { LabelPill } from "@/components/LabelPill";
import { OppBar } from "@/components/OppBar";
import { OpportunityChart } from "@/components/OpportunityChart";
import { SubscoreGrid } from "@/components/SubscoreGrid";

const FEEDS = ["all", "emerging", "hot_now", "trending", "saturated"] as const;
type Feed = (typeof FEEDS)[number];

const SORT_KEYS = ["opportunity", "demand", "competition", "momentum"] as const;
type SortKey = (typeof SORT_KEYS)[number];

const fmt = (n: number) => Math.round(n).toString().padStart(2, " ");

function StatCell({ label, value, color }: { label: string; value: string | number; color?: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <span style={{ color: "var(--muted)", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</span>
      <span className="mono" style={{ fontSize: 20, fontWeight: 700, color: color ?? "var(--fg)" }}>
        {value}
      </span>
    </div>
  );
}

function DetailPanel({
  slug,
  detail,
  onClose,
  onWatch,
  watching,
}: {
  slug: string;
  detail: NicheDetailOut | null;
  onClose: () => void;
  onWatch: (slug: string) => void;
  watching: boolean;
}) {
  if (!detail) {
    return (
      <div style={{ flex: "0 0 360px", borderLeft: "1px solid var(--border)", padding: "24px 20px", color: "var(--muted)", fontSize: 13 }}>
        Loading…
      </div>
    );
  }
  const s = detail.score;
  return (
    <div style={{ flex: "0 0 400px", borderLeft: "1px solid var(--border)", padding: "20px", overflowY: "auto", display: "flex", flexDirection: "column", gap: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 700 }}>{detail.label}</div>
          <div style={{ color: "var(--muted)", fontSize: 12, marginTop: 2 }}>{detail.category ?? "uncategorized"}</div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button
            onClick={() => onWatch(slug)}
            style={{
              padding: "4px 10px",
              borderRadius: 4,
              border: `1px solid ${watching ? "var(--accent)" : "var(--border)"}`,
              background: watching ? "rgba(79,140,255,0.12)" : "transparent",
              color: watching ? "var(--accent)" : "var(--muted)",
              fontSize: 12,
              cursor: "pointer",
            }}
          >
            {watching ? "Watching" : "Watch"}
          </button>
          <button
            onClick={onClose}
            style={{ background: "none", border: "none", color: "var(--muted)", cursor: "pointer", fontSize: 18, lineHeight: 1, padding: 2 }}
          >
            ×
          </button>
        </div>
      </div>

      {s && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, padding: "12px 0", borderTop: "1px solid var(--border)", borderBottom: "1px solid var(--border)" }}>
          <StatCell label="Opportunity" value={fmt(s.opportunity)} color="var(--accent)" />
          <StatCell label="Demand" value={fmt(s.demand)} color="var(--emerging)" />
          <StatCell label="Competition" value={fmt(s.competition)} color="var(--declining)" />
          <StatCell label="Momentum" value={s.momentum.toFixed(2)} />
          <StatCell label="Confidence" value={`${Math.round(s.confidence * 100)}%`} />
          <StatCell label="Listings" value={detail.active_listings.toLocaleString()} />
        </div>
      )}

      {detail.revenue_low_usd != null && (
        <div style={{ padding: "10px 12px", background: "var(--surface)", borderRadius: 6, border: "1px solid var(--border)" }}>
          <div style={{ color: "var(--muted)", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>Est. monthly revenue</div>
          <span className="mono" style={{ fontSize: 15, fontWeight: 600 }}>
            ${Math.round(detail.revenue_low_usd / 1000)}k – ${Math.round(detail.revenue_high_usd! / 1000)}k
          </span>
          <span style={{ color: "var(--muted)", fontSize: 11, marginLeft: 6 }}>range</span>
        </div>
      )}

      {detail.history.length > 1 && (
        <div>
          <div style={{ color: "var(--muted)", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 8 }}>28 day history</div>
          <OpportunityChart history={detail.history} />
        </div>
      )}

      {s && (
        <div>
          <div style={{ color: "var(--muted)", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 12 }}>Score breakdown</div>
          <SubscoreGrid score={s} />
        </div>
      )}

      {s && (
        <div style={{ fontSize: 11, color: "var(--muted)", paddingTop: 8, borderTop: "1px solid var(--border)" }}>
          Scored {s.date} · algo {s.algo_version}
        </div>
      )}
    </div>
  );
}

export function ExploreClient({
  initialNiches,
  watchlistIds,
}: {
  initialNiches: NicheOut[];
  watchlistIds: Set<string>;
}) {
  const [niches] = useState<NicheOut[]>(initialNiches);
  const [feed, setFeed] = useState<Feed>("all");
  const [sort, setSort] = useState<SortKey>("opportunity");
  const [search, setSearch] = useState("");
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [detail, setDetail] = useState<NicheDetailOut | null>(null);
  const [watching, setWatching] = useState<Set<string>>(new Set(watchlistIds));
  const [loadingSlug, setLoadingSlug] = useState<string | null>(null);

  const filtered = useMemo(() => {
    let out = niches;
    if (feed !== "all") out = out.filter((n) => n.score?.trend_label === (feed === "hot_now" ? "hot" : feed) || (feed === "hot_now" && n.score && n.score.demand >= 70 && n.score.momentum >= 1.0 && n.score.competition <= 65) || (feed === "trending" && (n.score?.trend_label === "rising" || n.score?.trend_label === "emerging")));
    if (search) out = out.filter((n) => n.label.toLowerCase().includes(search.toLowerCase()) || n.category?.toLowerCase().includes(search.toLowerCase()));
    return [...out].sort((a, b) => (b.score?.[sort] ?? 0) - (a.score?.[sort] ?? 0));
  }, [niches, feed, sort, search]);

  async function selectNiche(slug: string) {
    setSelectedSlug(slug);
    setDetail(null);
    setLoadingSlug(slug);
    try {
      const r = await fetch(`/api/niche/${slug}`);
      if (r.ok) setDetail(await r.json());
    } finally {
      setLoadingSlug(null);
    }
  }

  async function toggleWatch(slug: string) {
    const niche = niches.find((n) => n.slug === slug);
    if (!niche) return;
    if (watching.has(niche.id)) {
      await fetch(`/api/watchlist/${niche.id}`, { method: "DELETE" });
      setWatching((prev) => { const s = new Set(prev); s.delete(niche.id); return s; });
    } else {
      await fetch("/api/watchlist", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ niche_id: niche.id }) });
      setWatching((prev) => new Set(prev).add(niche.id));
    }
  }

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden" }}>
      {/* left: table pane */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {/* toolbar */}
        <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)", display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter niches…"
            style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 4, padding: "5px 10px", color: "var(--fg)", fontSize: 13, width: 200, outline: "none" }}
          />
          <div style={{ display: "flex", gap: 4 }}>
            {FEEDS.map((f) => (
              <button
                key={f}
                onClick={() => setFeed(f)}
                style={{
                  padding: "4px 10px", borderRadius: 4, fontSize: 12, cursor: "pointer",
                  border: `1px solid ${feed === f ? "var(--accent)" : "var(--border)"}`,
                  background: feed === f ? "rgba(79,140,255,0.12)" : "transparent",
                  color: feed === f ? "var(--accent)" : "var(--muted)",
                }}
              >
                {f.replace("_", " ")}
              </button>
            ))}
          </div>
          <div style={{ marginLeft: "auto", display: "flex", gap: 4, alignItems: "center" }}>
            <span style={{ color: "var(--muted)", fontSize: 12 }}>Sort</span>
            {SORT_KEYS.map((k) => (
              <button
                key={k}
                onClick={() => setSort(k)}
                style={{
                  padding: "4px 8px", borderRadius: 4, fontSize: 12, cursor: "pointer",
                  border: `1px solid ${sort === k ? "var(--border)" : "transparent"}`,
                  background: sort === k ? "var(--surface)" : "transparent",
                  color: sort === k ? "var(--fg)" : "var(--muted)",
                }}
              >
                {k}
              </button>
            ))}
          </div>
        </div>

        {/* table header */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 80px 80px 80px 72px 120px", gap: 8, padding: "8px 16px", borderBottom: "1px solid var(--border)", color: "var(--muted)", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.05em" }}>
          <span>Niche</span>
          <span className="mono" style={{ textAlign: "right" }}>Opp</span>
          <span className="mono" style={{ textAlign: "right" }}>Demand</span>
          <span className="mono" style={{ textAlign: "right" }}>Comp</span>
          <span></span>
          <span>Trend</span>
        </div>

        {/* rows */}
        <div style={{ overflowY: "auto", flex: 1 }}>
          {filtered.length === 0 && (
            <div style={{ padding: "40px 16px", color: "var(--muted)", fontSize: 13 }}>
              No niches match — run the nightly crawl and score pipeline first, or adjust the filter.
            </div>
          )}
          {filtered.map((n) => {
            const s = n.score;
            const label = s?.trend_label as TrendLabel | undefined;
            const isSelected = n.slug === selectedSlug;
            return (
              <div
                key={n.id}
                className={`niche-row${isSelected ? " selected" : ""}`}
                onClick={() => selectNiche(n.slug)}
                style={{ display: "grid", gridTemplateColumns: "1fr 80px 80px 80px 72px 120px", gap: 8, padding: "9px 16px", alignItems: "center" }}
              >
                <div>
                  <div style={{ fontWeight: 500, fontSize: 13 }}>{n.label}</div>
                  {n.category && <div style={{ color: "var(--muted)", fontSize: 11 }}>{n.category}</div>}
                </div>
                <span className="mono" style={{ textAlign: "right", fontSize: 13, color: "var(--accent)", fontWeight: 600 }}>
                  {s ? fmt(s.opportunity) : "—"}
                </span>
                <span className="mono" style={{ textAlign: "right", fontSize: 13 }}>
                  {s ? fmt(s.demand) : "—"}
                </span>
                <span className="mono" style={{ textAlign: "right", fontSize: 13 }}>
                  {s ? fmt(s.competition) : "—"}
                </span>
                <div style={{ display: "flex", justifyContent: "flex-end" }}>
                  {s && label && <OppBar value={s.opportunity} label={label} />}
                </div>
                <div>
                  {label ? <LabelPill label={label} /> : <span style={{ color: "var(--muted)" }}>—</span>}
                </div>
              </div>
            );
          })}
        </div>

        <div style={{ padding: "6px 16px", borderTop: "1px solid var(--border)", color: "var(--muted)", fontSize: 11 }}>
          {filtered.length} niches
        </div>
      </div>

      {/* right: detail panel */}
      {selectedSlug && (
        <DetailPanel
          slug={selectedSlug}
          detail={detail}
          onClose={() => { setSelectedSlug(null); setDetail(null); }}
          onWatch={toggleWatch}
          watching={detail ? watching.has(detail.id) : false}
        />
      )}
    </div>
  );
}
