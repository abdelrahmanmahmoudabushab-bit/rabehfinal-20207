"use client";

import { useState } from "react";
import { CheckCircle2, ClipboardCheck, Cpu, Lightbulb, Play, ShieldAlert } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Empty, PageHeader, Stat } from "@/components/app/bits";
import { api, refreshAll, useApi, type Review, type Status, type Usage } from "@/lib/api";
import { pct, signedMoney, timeAgo, tone } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export default function ReviewPage() {
  const { t } = useI18n();
  const { data } = useApi<Review[]>("/reviews", { refreshInterval: 30000 });
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    try {
      await api.post("/reviews/run");
      toast.success("Review finished");
      refreshAll();
    } catch (e) {
      toast.error(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title={t("review")}
        description="After every close the Reviewer grades each trade, writes lessons the agents read tomorrow, and only changes a rule if the change beats the live version on replay."
      >
        <Button onClick={run} disabled={busy}>
          <Play /> {busy ? "Reviewing…" : "Run review now"}
        </Button>
      </PageHeader>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          {!data ? (
            <Skeleton className="h-64 rounded-xl" />
          ) : !data.length ? (
            <Empty icon={<ClipboardCheck />}>The first review runs automatically at 16:30 ET, or run one now.</Empty>
          ) : (
            data.map((r) => <ReviewCard key={r.id} r={r} />)
          )}
        </div>
        <UsageCard />
      </div>
    </>
  );
}

function ReviewCard({ r }: { r: Review }) {
  const s = r.stats;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{r.day}</CardTitle>
        <CardDescription>{timeAgo(r.at)}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Trades" value={s.trades} sub={`${s.targets_hit} targets · ${s.stopped_out} stops`} />
          <Stat label="Win rate" value={s.trades ? `${Math.round(s.win_rate * 100)}%` : "—"} />
          <Stat label="P&L" value={signedMoney(s.pnl)} valueClass={tone(s.pnl)} />
          <Stat
            label="vs S&P 500"
            value={pct(s.account_return_pct - s.sp500_return_pct)}
            valueClass={tone(s.account_return_pct - s.sp500_return_pct)}
            sub={`S&P ${pct(s.sp500_return_pct)}`}
          />
        </div>
        <p className="text-sm leading-relaxed">{r.summary}</p>
        <div>
          <div className="mb-2 flex items-center gap-2 text-sm font-medium">
            <Lightbulb className="text-warn size-4" /> Lessons sent to the agents
          </div>
          <ul className="space-y-1.5">
            {r.lessons.map((l) => (
              <li key={l} className="flex gap-2 text-sm">
                <CheckCircle2 className="text-primary mt-0.5 size-3.5 shrink-0" /> {l}
              </li>
            ))}
          </ul>
        </div>
        <div className={cn("flex items-start gap-3 rounded-lg border p-3 text-sm", r.change_applied ? "border-gain/30 bg-gain/5" : "bg-muted/30")}>
          <ShieldAlert className={cn("mt-0.5 size-4 shrink-0", r.change_applied ? "text-gain" : "text-muted-foreground")} />
          <div>
            <div className="font-medium">
              {r.change_applied ? "Rule change applied" : "Live rules kept"}{" "}
              <Badge variant="muted" className="ms-1">
                threshold → {r.proposed_change.score_threshold}
              </Badge>
            </div>
            <div className="text-muted-foreground mt-0.5 text-xs">{r.change_verdict}</div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function UsageCard() {
  const { data } = useApi<Usage>("/usage", { refreshInterval: 15000 });
  const { data: status } = useApi<Status>("/status");
  return (
    <Card className="h-fit">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Cpu className="size-4" /> Agent usage (24h)
        </CardTitle>
        <CardDescription>
          {status?.claude ? `Claude · ${status.model}` : "No ANTHROPIC_API_KEY — agents run as transparent heuristics, free."}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <Stat label="Calls" value={data?.calls_24h ?? "—"} sub={data?.errors_24h ? `${data.errors_24h} errors` : undefined} />
          <Stat label="Est. cost" value={data ? `$${data.est_cost_24h.toFixed(2)}` : "—"} />
          <Stat label="Tokens in" value={data ? data.input_tokens_24h.toLocaleString() : "—"} sub={data ? `${data.cache_read_tokens_24h.toLocaleString()} cached` : undefined} />
          <Stat label="Tokens out" value={data ? data.output_tokens_24h.toLocaleString() : "—"} />
        </div>
        {!!data?.recent.length && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Agent</TableHead>
                <TableHead className="text-end">ms</TableHead>
                <TableHead className="text-end">When</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.recent.slice(0, 12).map((c, i) => (
                <TableRow key={i}>
                  <TableCell>
                    <span className={cn(!c.ok && "text-loss")}>{c.agent}</span>
                    {c.symbol && <span className="text-muted-foreground"> · {c.symbol}</span>}
                  </TableCell>
                  <TableCell className="tabular text-end">{c.ms}</TableCell>
                  <TableCell className="text-muted-foreground text-end text-xs">{timeAgo(c.at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
