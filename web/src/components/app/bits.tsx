"use client";

import { cn } from "@/lib/utils";

export function PageHeader({ title, description, children }: { title: string; description?: string; children?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="text-muted-foreground max-w-2xl text-sm">{description}</p>}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}

export function Stat({
  label,
  value,
  sub,
  valueClass,
  icon,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  valueClass?: string;
  icon?: React.ReactNode;
}) {
  return (
    <div className="bg-card rounded-xl border p-4 shadow-sm">
      <div className="text-muted-foreground flex items-center justify-between text-xs font-medium">
        {label}
        {icon}
      </div>
      <div className={cn("tabular mt-2 text-2xl font-semibold tracking-tight", valueClass)}>{value}</div>
      {sub && <div className="text-muted-foreground tabular mt-1 text-xs">{sub}</div>}
    </div>
  );
}

export function Empty({ icon, children }: { icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="text-muted-foreground flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed px-6 py-12 text-center text-sm">
      {icon && <div className="bg-muted grid size-10 place-items-center rounded-full [&_svg]:size-5">{icon}</div>}
      <div className="max-w-sm">{children}</div>
    </div>
  );
}

export function Sparkline({ data, className, positive }: { data: number[]; className?: string; positive?: boolean }) {
  if (data.length < 2) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const w = 100;
  const h = 28;
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * w},${h - ((v - min) / span) * (h - 2) - 1}`).join(" ");
  const up = positive ?? data[data.length - 1] >= data[0];
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className={cn("h-7 w-24", className)}>
      <polyline points={pts} fill="none" strokeWidth={1.5} vectorEffect="non-scaling-stroke" className={up ? "stroke-gain" : "stroke-loss"} />
    </svg>
  );
}

export function ScoreRing({ score, size = 52 }: { score: number; size?: number }) {
  const r = (size - 6) / 2;
  const c = 2 * Math.PI * r;
  const color = score >= 75 ? "stroke-gain" : score >= 60 ? "stroke-warn" : "stroke-loss";
  return (
    <div className="relative grid shrink-0 place-items-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} className="stroke-muted" strokeWidth={4} fill="none" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          className={color}
          strokeWidth={4}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - score / 100)}
        />
      </svg>
      <span className="tabular absolute text-sm font-semibold">{score}</span>
    </div>
  );
}

/** A horizontal bar showing where price sits between stop and target. */
export function RangeBar({ stop, entry, target, price }: { stop: number; entry: number; target: number; price?: number }) {
  const lo = stop;
  const hi = target;
  const span = hi - lo || 1;
  const pos = (v: number) => `${Math.min(100, Math.max(0, ((v - lo) / span) * 100))}%`;
  return (
    <div className="relative h-2 w-full rounded-full bg-gradient-to-r from-loss/40 via-muted to-gain/40 rtl:bg-gradient-to-l">
      <div className="bg-foreground/60 absolute top-1/2 h-3 w-px -translate-y-1/2" style={{ insetInlineStart: pos(entry) }} />
      {price != null && (
        <div
          className="border-background bg-foreground absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 rtl:translate-x-1/2"
          style={{ insetInlineStart: pos(price) }}
        />
      )}
    </div>
  );
}
