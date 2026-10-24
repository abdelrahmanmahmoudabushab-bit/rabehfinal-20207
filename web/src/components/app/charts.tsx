"use client";

import { Area, AreaChart, CartesianGrid, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { clock } from "@/lib/format";

function ChartTip({ active, payload, label }: { active?: boolean; payload?: { name: string; value: number; color: string }[]; label?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-popover rounded-lg border px-3 py-2 text-xs shadow-md">
      <div className="text-muted-foreground mb-1">{clock(label)}</div>
      {payload.map((p) => (
        <div key={p.name} className="tabular flex items-center gap-2">
          <span className="size-2 rounded-full" style={{ background: p.color }} />
          <span className="text-muted-foreground">{p.name}</span>
          <span className="ms-auto font-medium">
            {p.value >= 0 ? "+" : ""}
            {p.value.toFixed(2)}%
          </span>
        </div>
      ))}
    </div>
  );
}

export function PerformanceChart({ data }: { data: { t: string; you: number; sp500: number }[] }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
        <defs>
          <linearGradient id="youFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-chart-1)" stopOpacity={0.35} />
            <stop offset="100%" stopColor="var(--color-chart-1)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} stroke="var(--color-border)" />
        <XAxis dataKey="t" tickFormatter={clock} tickLine={false} axisLine={false} minTickGap={48} tick={{ fill: "var(--color-muted-foreground)", fontSize: 11 }} />
        <YAxis tickFormatter={(v) => `${v.toFixed(2)}%`} tickLine={false} axisLine={false} width={52} tick={{ fill: "var(--color-muted-foreground)", fontSize: 11 }} />
        <Tooltip content={<ChartTip />} />
        <Area type="monotone" dataKey="you" name="You" stroke="var(--color-chart-1)" strokeWidth={2} fill="url(#youFill)" isAnimationActive={false} />
        <Line type="monotone" dataKey="sp500" name="S&P 500" stroke="var(--color-chart-2)" strokeWidth={1.5} strokeDasharray="4 4" dot={false} isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function PriceChart({ data, up }: { data: { t: string; c: number }[]; up: boolean }) {
  const color = up ? "var(--color-gain)" : "var(--color-loss)";
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={data} margin={{ top: 8, right: 4, left: -8, bottom: 0 }}>
        <defs>
          <linearGradient id="priceFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.3} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} stroke="var(--color-border)" />
        <XAxis dataKey="t" tickFormatter={clock} tickLine={false} axisLine={false} minTickGap={48} tick={{ fill: "var(--color-muted-foreground)", fontSize: 11 }} />
        <YAxis domain={["auto", "auto"]} tickLine={false} axisLine={false} width={56} tick={{ fill: "var(--color-muted-foreground)", fontSize: 11 }} />
        <Tooltip
          formatter={(v) => [`$${Number(v).toFixed(2)}`, "Price"]}
          labelFormatter={(l) => clock(String(l))}
          contentStyle={{ background: "var(--color-popover)", border: "1px solid var(--color-border)", borderRadius: 8, fontSize: 12 }}
        />
        <Area type="monotone" dataKey="c" stroke={color} strokeWidth={2} fill="url(#priceFill)" isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}
