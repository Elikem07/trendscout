"use client";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";
import { ScoreOut } from "@/lib/api";

export function OpportunityChart({ history }: { history: ScoreOut[] }) {
  const data = history.map((h) => ({
    date: h.date.slice(5),   // MM-DD
    opp: Math.round(h.opportunity),
    demand: Math.round(h.demand),
    competition: Math.round(h.competition),
  }));

  return (
    <ResponsiveContainer width="100%" height={160}>
      <AreaChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
        <defs>
          <linearGradient id="oppGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="var(--accent)" stopOpacity={0.25} />
            <stop offset="95%" stopColor="var(--accent)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="date"
          tick={{ fill: "var(--muted)", fontSize: 10 }}
          tickLine={false}
          axisLine={false}
          interval="preserveStartEnd"
        />
        <YAxis
          domain={[0, 100]}
          tick={{ fill: "var(--muted)", fontSize: 10 }}
          tickLine={false}
          axisLine={false}
        />
        <Tooltip
          contentStyle={{
            background: "var(--surface-2)",
            border: "1px solid var(--border)",
            borderRadius: 4,
            fontSize: 12,
          }}
          labelStyle={{ color: "var(--muted)" }}
          itemStyle={{ color: "var(--fg)" }}
        />
        <Area
          type="monotone"
          dataKey="opp"
          name="Opportunity"
          stroke="var(--accent)"
          strokeWidth={1.5}
          fill="url(#oppGrad)"
          dot={false}
        />
        <Area
          type="monotone"
          dataKey="demand"
          name="Demand"
          stroke="var(--emerging)"
          strokeWidth={1}
          fill="none"
          dot={false}
          strokeDasharray="4 2"
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
