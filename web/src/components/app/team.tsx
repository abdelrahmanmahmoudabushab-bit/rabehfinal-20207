"use client";

import { AlertTriangle, ExternalLink } from "lucide-react";

import type { Earnings, Filing, Ratings, TeamReports } from "@/lib/api";
import { cn } from "@/lib/utils";

function By({ by }: { by?: string }) {
  if (!by) return null;
  return (
    <span className="text-muted-foreground rounded-sm border px-1 font-mono text-[9px] uppercase">{by === "claude" ? "Claude" : "rules"}</span>
  );
}

function Row({ name, by, right, children }: { name: string; by?: string; right?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5 border-b py-3 last:border-b-0">
      <div className="flex items-center gap-2">
        <span className="text-xs font-semibold">{name}</span>
        <By by={by} />
        <span className="ms-auto">{right}</span>
      </div>
      {children}
    </div>
  );
}

/** The specialists' reports that the Analyst combined. */
export function TeamReportsView({ team, compact }: { team: TeamReports; compact?: boolean }) {
  const { news, chart, company, mood } = team;
  if (!news && !chart && !company && !mood) {
    return <p className="text-muted-foreground text-xs">This idea was made before the specialist agents were added.</p>;
  }
  return (
    <div>
      {news && (
        <Row
          name="News reader"
          by={news.by}
          right={<span className={cn("num text-xs", news.sentiment > 0 ? "text-gain" : news.sentiment < 0 ? "text-loss" : "")}>{news.sentiment > 0 ? "+" : ""}{news.sentiment}/100</span>}
        >
          <p className="text-xs leading-relaxed">{news.summary}</p>
          {!compact && (
            <ul className="text-muted-foreground space-y-0.5 text-[11px]">
              {news.key_points.map((k) => (
                <li key={k}>— {k}</li>
              ))}
            </ul>
          )}
          <div className="flex gap-1.5">
            <Flag on={news.company_specific}>{news.company_specific ? "company news" : "market-wide"}</Flag>
            {news.priced_in && <Flag on warn>priced in?</Flag>}
          </div>
        </Row>
      )}
      {chart && (
        <Row name="Chart reader" by={chart.by} right={<span className="num text-xs">{chart.strength}/100</span>}>
          <p className="text-xs leading-relaxed">{chart.setup}</p>
          <div className="text-muted-foreground flex gap-3 font-mono text-[11px]">
            <span>TREND {chart.trend.toUpperCase()}</span>
            <span>SUP {chart.support.toFixed(2)}</span>
            <span>RES {chart.resistance.toFixed(2)}</span>
          </div>
        </Row>
      )}
      {company && (
        <Row
          name="Company checker"
          by={company.by}
          right={<span className={cn("font-mono text-[11px] uppercase", company.health === "strong" ? "text-gain" : company.health === "weak" ? "text-loss" : "")}>{company.health}</span>}
        >
          {!compact && <p className="text-xs leading-relaxed">{company.summary}</p>}
          <p className="text-muted-foreground text-[11px]">Analysts: {company.analyst_view}</p>
          {company.red_flags.map((f) => (
            <div key={f} className="text-loss flex items-start gap-1.5 text-[11px]">
              <AlertTriangle className="mt-px size-3 shrink-0" /> {f}
            </div>
          ))}
        </Row>
      )}
      {mood && (
        <Row name="Market mood" by={mood.by} right={<span className="font-mono text-[11px] uppercase">{mood.level}</span>}>
          <p className="text-xs leading-relaxed">{mood.summary}</p>
          {!compact && mood.watch_out_for.length > 0 && <p className="text-muted-foreground text-[11px]">Watch: {mood.watch_out_for.join(" · ")}</p>}
        </Row>
      )}
    </div>
  );
}

function Flag({ on, warn, children }: { on?: boolean; warn?: boolean; children: React.ReactNode }) {
  return (
    <span className={cn("rounded-sm border px-1 font-mono text-[9px] uppercase", warn ? "border-warn text-warn" : on ? "border-foreground/50" : "text-muted-foreground")}>
      {children}
    </span>
  );
}

export function EarningsBlock({ e }: { e: Earnings }) {
  if (!e.next_date && !e.history.length) return <p className="text-muted-foreground text-xs">No earnings data (add FINNHUB_API_KEY).</p>;
  const soon = e.days_until != null && e.days_until <= 1;
  const max = Math.max(1, ...e.history.map((h) => Math.abs(h.surprise_pct ?? 0)));
  return (
    <div className="space-y-3">
      {e.next_date && (
        <div className={cn("flex items-baseline justify-between rounded-sm border px-2 py-1.5", soon && "border-warn text-warn")}>
          <span className="font-mono text-xs">
            {e.next_date} {e.next_hour ? `· ${e.next_hour === "bmo" ? "before open" : e.next_hour === "amc" ? "after close" : e.next_hour}` : ""}
          </span>
          <span className="font-mono text-[11px]">{e.days_until === 0 ? "TODAY" : e.days_until === 1 ? "TOMORROW" : `in ${e.days_until}d`}</span>
        </div>
      )}
      {soon && <p className="text-warn text-[11px]">No new positions: overnight gap risk around the report.</p>}
      {e.history.length > 0 && (
        <div className="space-y-1">
          <div className="text-muted-foreground font-mono text-[10px] uppercase">EPS surprise, last {e.history.length} quarters</div>
          {e.history.map((h) => {
            const v = h.surprise_pct ?? 0;
            return (
              <div key={h.period} className="grid grid-cols-[72px_1fr_52px] items-center gap-2 font-mono text-[11px]">
                <span className="text-muted-foreground">{h.period}</span>
                <div className="bg-muted relative h-1.5">
                  <div className={cn("absolute inset-y-0 start-0", v >= 0 ? "bg-gain" : "bg-loss")} style={{ width: `${(Math.abs(v) / max) * 100}%` }} />
                </div>
                <span className={cn("text-end", v >= 0 ? "text-gain" : "text-loss")}>{v >= 0 ? "+" : ""}{v.toFixed(1)}%</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function RatingsBlock({ r }: { r: Ratings | null }) {
  if (!r || !r.total) return <p className="text-muted-foreground text-xs">No analyst ratings (add FINNHUB_API_KEY).</p>;
  const parts = [
    ["Strong buy", r.strong_buy, "bg-foreground"],
    ["Buy", r.buy, "bg-foreground/70"],
    ["Hold", r.hold, "bg-foreground/35"],
    ["Sell", r.sell, "bg-loss/70"],
    ["Strong sell", r.strong_sell, "bg-loss"],
  ] as const;
  return (
    <div className="space-y-2">
      <div className="flex h-2 overflow-hidden">
        {parts.map(([k, n, c]) => (n ? <div key={k} className={c} style={{ width: `${(n / r.total) * 100}%` }} title={`${k}: ${n}`} /> : null))}
      </div>
      <div className="text-muted-foreground flex justify-between font-mono text-[10px]">
        <span>BUY {r.strong_buy + r.buy}</span>
        <span>HOLD {r.hold}</span>
        <span>SELL {r.sell + r.strong_sell}</span>
        <span className="text-foreground">{r.score?.toFixed(1)}/5</span>
      </div>
      <div className="text-muted-foreground text-[10px]">{r.total} analysts · {r.period}</div>
    </div>
  );
}

export function FilingsList({ items }: { items: Filing[] }) {
  if (!items.length) return <p className="text-muted-foreground text-xs">No recent filings.</p>;
  return (
    <ul className="space-y-2">
      {items.map((f, i) => (
        <li key={f.form + f.filed + i} className="grid grid-cols-[52px_1fr] gap-2">
          <span className="h-fit rounded-sm border px-1 text-center font-mono text-[10px]">{f.form}</span>
          <span className="min-w-0">
            {f.url ? (
              <a href={f.url} target="_blank" rel="noreferrer" className="flex items-start gap-1 text-xs leading-snug hover:underline">
                {f.description} <ExternalLink className="mt-0.5 size-3 shrink-0 opacity-60" />
              </a>
            ) : (
              <span className="text-xs leading-snug">{f.description}</span>
            )}
            <span className="text-muted-foreground block font-mono text-[10px]">{f.filed}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}
