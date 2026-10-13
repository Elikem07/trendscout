"use client";
import { LABEL_COLOR, TrendLabel } from "@/lib/api";

export function OppBar({
  value,
  label,
}: {
  value: number;
  label: TrendLabel;
}) {
  return (
    <div className="opp-bar" style={{ width: 72 }}>
      <div
        className="opp-bar-fill"
        style={{
          width: `${Math.round(value)}%`,
          background: LABEL_COLOR[label],
        }}
      />
    </div>
  );
}
