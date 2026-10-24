"use client";

import { Fragment, useState } from "react";
import { ArrowDown, ArrowRight, CheckCircle2, CornerDownLeft, XCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/app/bits";
import { MOOD_STYLE } from "@/components/app/mood-chip";
import { TeamReportsView } from "@/components/app/team";
import { useApi, type AgentInfo, type AgentsOverview, type Mood, type Proposal, type Source } from "@/lib/api";
import { clock, money, pct, timeAgo, tone } from "@/lib/format";
import { cn } from "@/lib/utils";

const STAGES: { title: string; note: string; ids: string[]; flow?: "row" | "chain"; edge: string; highlight?: boolean }[] = [
  { title: "1 · Clean and check", note: "plain code", ids: ["data_checks"], edge: "clean data + feature scores" },
  { title: "2 · Filter", note: "plain code, free, fast", ids: ["scanner", "halal"], edge: "only the interesting stocks" },
  { title: "3 · Specialists", note: "run side by side", ids: ["news", "chart", "company", "mood"], edge: "four reports" },
  { title: "4 · Decide", note: "each must agree to go on", ids: ["analyst", "devil", "manager"], flow: "chain", edge: "trade proposal" },
  { title: "5 · Safety check", note: "plain code, final say", ids: ["risk"], highlight: true, edge: "approved order" },
  { title: "6 · Trade", note: "your broker", ids: ["broker"], edge: "results" },
  { title: "7 · Learn", note: "after the close", ids: ["reviewer"], edge: "" },
];

const KIND: Record<AgentInfo["kind"], string> = { claude: "Claude", rules: "Rules", code: "Code" };

export default function AgentsPage() {
  const { data } = useApi<AgentsOverview>("/agents", { refreshInterval: 15000 });
  const { data: sources } = useApi<Source[]>("/sources", { refreshInterval: 60000 });
  const [sel, setSel] = useState("analyst");
  const byId = Object.fromEntries((data?.agents ?? []).map((a) => [a.id, a]));
  const selected = byId[sel];

  return (
    <>
      <PageHeader
        title="How the AI agents work together"
        description="Every stock flows top to bottom. Each step can say no, and every no is logged. Claude agents think; plain code checks the data and has the final say on risk."
      >
        {data && (
          <div className="flex gap-2">
            <Badge variant="outline" className="font-mono uppercase">team: {data.team_mode}</Badge>
            <Badge variant="outline" className="font-mono">{data.claude ? data.model : "rule-based (no Claude key)"}</Badge>
          </div>
        )}
      </PageHeader>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
        <Card className="py-4">
          <CardContent className="px-4">
            <SourcesStrip sources={sources} />
            <Edge label="raw data" />
            {!data ? (
              <Skeleton className="h-[640px]" />
            ) : (
              STAGES.map((st, i) => (
                <Fragment key={st.title}>
                  <div className={cn("rounded-md border p-3", st.highlight ? "border-foreground border-2" : "bg-muted/30")}>
                    <div className="mb-2 flex items-baseline justify-between">
                      <span className="font-mono text-[11px] font-bold tracking-wide uppercase">{st.title}</span>
                      <span className="text-muted-foreground text-[11px]">{st.note}</span>
                    </div>
                    <div className={cn("grid gap-2", st.ids.length === 4 ? "grid-cols-2 md:grid-cols-4" : st.ids.length === 3 ? "md:grid-cols-[1fr_auto_1fr_auto_1fr]" : st.ids.length === 2 ? "grid-cols-2" : "")}>
                      {st.ids.map((id, j) => (
                        <Fragment key={id}>
                          {st.flow === "chain" && j > 0 && <ArrowRight className="text-muted-foreground hidden size-4 self-center md:block rtl:rotate-180" />}
                          {byId[id] && <Node a={byId[id]} active={sel === id} onClick={() => setSel(id)} />}
                        </Fragment>
                      ))}
                    </div>
                  </div>
                  {st.edge && <Edge label={st.edge} />}
                  {i === STAGES.length - 1 && (
                    <div className="text-muted-foreground mt-2 flex items-center gap-2 font-mono text-[11px]">
                      <CornerDownLeft className="size-3.5" /> lessons go back to the Analyst the next morning; a rule only changes if it beats the live version on replay
                    </div>
                  )}
                </Fragment>
              ))
            )}
            {byId.coach && (
              <div className="mt-4 border-t pt-4">
                <div className="text-muted-foreground mb-2 font-mono text-[11px] uppercase">Talks to you</div>
                <Node a={byId.coach} active={sel === "coach"} onClick={() => setSel("coach")} />
              </div>
            )}
          </CardContent>
        </Card>

        <div className="space-y-4 lg:sticky lg:top-16 lg:h-fit">
          <Card>
            <CardHeader>
              <CardTitle>{selected?.name ?? "…"}</CardTitle>
              <CardDescription>
                {selected && (
                  <span className="font-mono text-[11px] uppercase">
                    {KIND[selected.kind]} · {selected.when}
                    {selected.module && ` · ${selected.module}`}
                  </span>
                )}
              </CardDescription>
            </CardHeader>
            {selected && (
              <CardContent className="space-y-4 text-sm">
                <p className="leading-relaxed">{selected.job}</p>
                <div>
                  <div className="text-muted-foreground mb-1 font-mono text-[10px] uppercase">Reads</div>
                  <div className="flex flex-wrap gap-1">
                    {selected.reads.map((r) => (
                      <span key={r} className="rounded-sm border px-1.5 py-0.5 text-[11px]">{r}</span>
                    ))}
                  </div>
                </div>
                <div>
                  <div className="text-muted-foreground mb-1 font-mono text-[10px] uppercase">Hands on</div>
                  <span className="text-[13px]">{selected.writes}</span>
                </div>
                {selected.kind !== "code" && (
                  <div className="grid grid-cols-3 gap-2 border-t pt-3 font-mono text-[11px]">
                    <div><div className="text-muted-foreground text-[10px]">CALLS 24H</div>{selected.calls_24h}</div>
                    <div><div className="text-muted-foreground text-[10px]">AVG</div>{selected.avg_ms != null ? `${(selected.avg_ms / 1000).toFixed(1)}s` : "—"}</div>
                    <div><div className="text-muted-foreground text-[10px]">TOKENS</div>{selected.tokens_24h.toLocaleString()}</div>
                  </div>
                )}
                {selected.kind === "rules" && (
                  <p className="text-muted-foreground text-[11px]">
                    Running as transparent rules right now. {data?.claude ? "Set AGENT_TEAM=full to make it a Claude agent." : "Add ANTHROPIC_API_KEY to run it on Claude."}
                  </p>
                )}
              </CardContent>
            )}
          </Card>
          <TeamModeCard mode={data?.team_mode} />
        </div>
      </div>

      <RunTrace runs={data?.runs} />
      <MoodCard />
      <SourcesTable sources={sources} />
    </>
  );
}

function Node({ a, active, onClick }: { a: AgentInfo; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "bg-background flex w-full cursor-pointer flex-col items-start gap-1 rounded-sm border p-2.5 text-start transition-colors",
        active ? "border-foreground ring-foreground ring-1" : "hover:border-foreground/50",
      )}
    >
      <div className="flex w-full items-center gap-2">
        <span className="text-[13px] font-semibold">{a.name}</span>
        <span
          className={cn(
            "ms-auto rounded-sm px-1 font-mono text-[9px] uppercase",
            a.kind === "claude" ? "bg-foreground text-background" : "border",
          )}
        >
          {KIND[a.kind]}
        </span>
      </div>
      <span className="text-muted-foreground line-clamp-2 text-[11px] leading-snug">{a.job}</span>
      {a.kind !== "code" && a.calls_24h > 0 && <span className="text-muted-foreground font-mono text-[10px]">{a.calls_24h} calls today</span>}
    </button>
  );
}

function Edge({ label }: { label: string }) {
  return (
    <div className="text-muted-foreground flex items-center justify-center gap-2 py-1.5 font-mono text-[10px]">
      <ArrowDown className="size-3.5" /> {label}
    </div>
  );
}

const STATUS: Record<Source["status"], { label: string; cls: string }> = {
  connected: { label: "connected", cls: "bg-gain" },
  simulated: { label: "simulated", cls: "bg-warn" },
  missing_key: { label: "needs key", cls: "bg-muted-foreground" },
  not_wired: { label: "planned", cls: "bg-transparent border border-muted-foreground" },
};

function SourcesStrip({ sources }: { sources?: Source[] }) {
  return (
    <div className="rounded-md border p-3">
      <div className="mb-2 flex items-baseline justify-between">
        <span className="font-mono text-[11px] font-bold tracking-wide uppercase">0 · Data in</span>
        <a href="#sources" className="text-muted-foreground text-[11px] hover:underline">all sources ↓</a>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {(sources ?? []).filter((s) => s.status !== "not_wired").map((s) => (
          <span key={s.name} className="flex items-center gap-1.5 rounded-sm border px-1.5 py-0.5 text-[11px]">
            <span className={cn("size-1.5 rounded-full", STATUS[s.status].cls)} /> {s.name}
          </span>
        ))}
      </div>
    </div>
  );
}

function TeamModeCard({ mode }: { mode?: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Team size</CardTitle>
        <CardDescription>Set with AGENT_TEAM in api/.env</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-xs">
        {[
          ["starter", "Specialists run as free rules; Claude runs the Analyst, Devil's advocate, Manager, Reviewer and Coach. About 3 Claude calls per stock that passes the filter."],
          ["full", "Every specialist is its own Claude agent, run in parallel. About 6 Claude calls per stock, roughly twice the cost, deeper reading."],
        ].map(([k, v]) => (
          <div key={k} className={cn("rounded-sm border p-2", mode === k && "border-foreground")}>
            <div className="mb-0.5 font-mono text-[11px] font-bold uppercase">{k}{mode === k && " · active"}</div>
            <div className="text-muted-foreground leading-relaxed">{v}</div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

// ---- live trace of a real run -------------------------------------------------------------------
function RunTrace({ runs }: { runs?: Proposal[] }) {
  const [id, setId] = useState<string | null>(null);
  const run = runs?.find((r) => String(r.id) === id) ?? runs?.[0];
  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle>Watch them work</CardTitle>
        <CardDescription>The real hand-offs for one stock, in order. Pick any recent run.</CardDescription>
      </CardHeader>
      <CardContent>
        {!runs ? (
          <Skeleton className="h-60" />
        ) : !run ? (
          <p className="text-muted-foreground text-sm">No runs yet. The first one appears when a stock gets past the filter, or use “Analyze with AI” on the chart.</p>
        ) : (
          <div className="space-y-4">
            <Select value={String(run.id)} onValueChange={setId}>
              <SelectTrigger className="w-full font-mono text-xs sm:w-80">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {runs.map((r) => (
                  <SelectItem key={r.id} value={String(r.id)} className="font-mono text-xs">
                    #{r.id} {r.symbol} · score {r.score} · {r.status} · {timeAgo(r.created_at)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <ol className="relative space-y-4 border-s ps-5">
              <Step n="Specialists" sub="News reader, Chart reader, Company checker, Market mood">
                <TeamReportsView team={run.team ?? {}} compact />
              </Step>
              <Step n="Analyst" sub={`score ${run.analyst.score}/100 · ${run.analyst.direction}`}>
                <p className="text-sm leading-relaxed">{run.analyst.thesis}</p>
              </Step>
              <Step n="Devil's advocate" sub={`severity ${run.devil.severity}/5${run.devil.deal_breaker ? " · deal breaker" : ""}`}>
                <p className="text-sm leading-relaxed">{run.devil.objection}</p>
              </Step>
              <Step n="Manager" sub={`${run.manager.decision} · objection ${run.manager.objection_answered ? "answered" : "not answered"}`}>
                <p className="text-sm leading-relaxed">{run.manager.rebuttal}</p>
                <div className="mt-2 grid max-w-md grid-cols-4 border font-mono text-[11px]">
                  {[["Entry", money(run.entry)], ["Stop", money(run.stop)], ["Target", money(run.target)], ["Qty", String(run.qty)]].map(([k, v]) => (
                    <div key={k} className="border-e px-2 py-1 last:border-e-0">
                      <div className="text-muted-foreground text-[9px] uppercase">{k}</div>
                      {v}
                    </div>
                  ))}
                </div>
              </Step>
              <Step n="Risk engine" sub="plain code, final say">
                <ul className="grid gap-1 sm:grid-cols-2">
                  {run.risk_checks.map((c) => (
                    <li key={c.name} className="flex items-start gap-1.5 text-xs">
                      {c.passed ? <CheckCircle2 className="text-gain mt-px size-3.5 shrink-0" /> : <XCircle className="text-loss mt-px size-3.5 shrink-0" />}
                      <span className={cn(!c.passed && "text-loss")}>{c.detail}</span>
                    </li>
                  ))}
                </ul>
              </Step>
              <Step n="Outcome" sub={run.status.toUpperCase()}>
                <p className="text-muted-foreground text-xs">{run.status_reason ?? (run.status === "executed" ? "Bracket order sent to the broker." : run.status === "pending" ? "Waiting for your approval." : "")}</p>
              </Step>
            </ol>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Step({ n, sub, children }: { n: string; sub: string; children: React.ReactNode }) {
  return (
    <li>
      <span className="bg-foreground absolute -start-[5px] mt-1.5 size-2.5 rounded-full" />
      <div className="mb-1 flex flex-wrap items-baseline gap-2">
        <span className="text-sm font-semibold">{n}</span>
        <span className="text-muted-foreground font-mono text-[11px]">{sub}</span>
      </div>
      {children}
    </li>
  );
}

// ---- market mood ---------------------------------------------------------------------------------
function MoodCard() {
  const { data: m } = useApi<Mood>("/mood", { refreshInterval: 15000 });
  return (
    <Card className="mt-4" id="mood">
      <CardHeader>
        <CardTitle>Market mood</CardTitle>
        <CardDescription>Says when to be careful. Calm: full size. Careful: half size. Stormy: no new trades.</CardDescription>
      </CardHeader>
      <CardContent>
        {!m?.level ? (
          <Skeleton className="h-40" />
        ) : (
          <div className="grid gap-6 lg:grid-cols-[260px_1fr_1fr]">
            <div className="space-y-2">
              <div className={cn("inline-flex items-center gap-2 rounded-sm border px-2 py-1 font-mono text-sm font-bold uppercase", MOOD_STYLE[m.level])}>
                <span className="size-2 rounded-full bg-current" /> {m.level}
              </div>
              <p className="text-sm leading-relaxed">{m.report?.summary || m.summary}</p>
              <ul className="text-muted-foreground space-y-0.5 text-xs">
                {m.reasons.map((r) => <li key={r}>— {r}</li>)}
              </ul>
              {m.source && <p className="text-muted-foreground font-mono text-[10px] uppercase">source: {m.source} · agent: {m.report?.by}</p>}
            </div>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 self-start">
              {[
                ["VIX", m.vix?.toFixed(2), m.vix_change != null ? `${m.vix_change > 0 ? "+" : ""}${m.vix_change.toFixed(2)}` : "", m.vix_change != null ? -m.vix_change : 0],
                ["S&P 500 today", pct(m.spy_change_pct), "", m.spy_change_pct],
                ["Breadth", `${m.breadth_pct.toFixed(0)}% up`, "", m.breadth_pct - 50],
                ["Fed funds", m.fed_funds != null ? `${m.fed_funds.toFixed(2)}%` : "—", "", 0],
                ["10-year", m.ten_year != null ? `${m.ten_year.toFixed(2)}%` : "—", m.ten_year_change_bp != null ? `${m.ten_year_change_bp > 0 ? "+" : ""}${m.ten_year_change_bp}bp` : "", 0],
                ["Oil (WTI)", m.oil != null ? `$${m.oil.toFixed(2)}` : "—", m.oil_change_pct != null ? pct(m.oil_change_pct) : "", 0],
              ].map(([k, v, d, t]) => (
                <div key={String(k)} className="border-b border-dashed pb-1">
                  <dt className="text-muted-foreground text-[11px]">{k}</dt>
                  <dd className="num text-sm">
                    {v ?? "—"} <span className={cn("text-[11px]", tone(Number(t)))}>{d}</span>
                  </dd>
                </div>
              ))}
            </dl>
            <div>
              <div className="text-muted-foreground mb-2 font-mono text-[10px] uppercase">Economic calendar</div>
              {m.events.length ? (
                <ul className="space-y-1.5">
                  {m.events.map((e) => (
                    <li key={e.time + e.event} className="grid grid-cols-[52px_1fr_auto] items-baseline gap-2 text-xs">
                      <span className="num text-muted-foreground">{clock(e.time)}</span>
                      <span>{e.event}</span>
                      <span className={cn("font-mono text-[10px] uppercase", e.impact === "high" ? "text-warn" : "text-muted-foreground")}>{e.impact}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-muted-foreground text-xs">No calendar (add FINNHUB_API_KEY or FMP_API_KEY).</p>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ---- data sources --------------------------------------------------------------------------------
function SourcesTable({ sources }: { sources?: Source[] }) {
  return (
    <Card className="mt-4" id="sources">
      <CardHeader>
        <CardTitle>Data sources</CardTitle>
        <CardDescription>Where every number comes from. Keys live in api/.env on the server, never in the browser.</CardDescription>
      </CardHeader>
      <CardContent>
        {!sources ? (
          <Skeleton className="h-40" />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Source</TableHead>
                <TableHead>Provides</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Setting</TableHead>
                <TableHead>Note</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sources.map((s) => (
                <TableRow key={s.name}>
                  <TableCell className="font-medium">{s.name}</TableCell>
                  <TableCell className="text-muted-foreground max-w-80 text-xs whitespace-normal">{s.provides}</TableCell>
                  <TableCell>
                    <span className="flex items-center gap-1.5 font-mono text-[11px] uppercase">
                      <span className={cn("size-2 rounded-full", STATUS[s.status].cls)} /> {STATUS[s.status].label}
                    </span>
                  </TableCell>
                  <TableCell className="font-mono text-[11px]">{s.env || "—"}</TableCell>
                  <TableCell className="text-muted-foreground text-xs whitespace-normal">{s.note}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
