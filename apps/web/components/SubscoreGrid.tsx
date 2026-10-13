"use client";
import { ScoreOut } from "@/lib/api";

function Bar({ value }: { value: number | null }) {
  if (value == null) return <span style={{ color: "var(--muted)" }}>—</span>;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <div
        style={{
          width: 48,
          height: 3,
          borderRadius: 2,
          background: "var(--border)",
          overflow: "hidden",
          flexShrink: 0,
        }}
      >
        <div
          style={{
            width: `${Math.round(value)}%`,
            height: "100%",
            background: "var(--accent)",
            borderRadius: 2,
          }}
        />
      </div>
      <span className="mono" style={{ fontSize: 11, color: "var(--muted)" }}>
        {Math.round(value)}
      </span>
    </div>
  );
}

export function SubscoreGrid({ score }: { score: ScoreOut }) {
  const demand = score.subscores.demand ?? {};
  const comp = score.subscores.competition ?? {};
  const DEMAND_LABELS: Record<string, string> = {
    engagement_velocity: "Engagement velocity",
    search_interest: "Search interest",
    review_velocity: "Review velocity",
    social_engagement: "Social engagement",
    social_breadth: "Social breadth",
    demand_level: "Demand level",
  };
  const COMP_LABELS: Record<string, string> = {
    listing_count: "Listing count",
    young_listing_share: "Young listing share",
    new_listing_velocity: "New listing velocity",
    price_compression: "Price compression",
    concentration: "Concentration (HHI)",
    review_moat: "Review moat",
  };
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 24px" }}>
      <div>
        <div style={{ color: "var(--muted)", fontSize: 11, fontWeight: 600, letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: 8 }}>Demand drivers</div>
        {Object.entries(DEMAND_LABELS).map(([k, label]) => (
          <div key={k} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6, gap: 8 }}>
            <span style={{ color: "var(--muted)", fontSize: 12, flex: 1 }}>{label}</span>
            <Bar value={demand[k] ?? null} />
          </div>
        ))}
      </div>
      <div>
        <div style={{ color: "var(--muted)", fontSize: 11, fontWeight: 600, letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: 8 }}>Competition drivers</div>
        {Object.entries(COMP_LABELS).map(([k, label]) => (
          <div key={k} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6, gap: 8 }}>
            <span style={{ color: "var(--muted)", fontSize: 12, flex: 1 }}>{label}</span>
            <Bar value={comp[k] ?? null} />
          </div>
        ))}
      </div>
    </div>
  );
}
