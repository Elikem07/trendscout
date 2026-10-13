"use client";
import { LABEL_COLOR, TrendLabel } from "@/lib/api";

export function LabelPill({ label }: { label: TrendLabel }) {
  return (
    <span
      className="label-pill"
      style={{
        color: LABEL_COLOR[label],
        background: `${LABEL_COLOR[label]}18`,
      }}
    >
      {label}
    </span>
  );
}
