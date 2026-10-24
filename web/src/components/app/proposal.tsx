"use client";

import { useState } from "react";
import { Bot, Check, CheckCircle2, ShieldCheck, Sparkles, Swords, X, XCircle } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Separator } from "@/components/ui/misc";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { RangeBar, ScoreRing } from "@/components/app/bits";
import { BacktestBadge, BacktestPanel } from "@/components/app/backtest-panel";
import { TeamReportsView } from "@/components/app/team";
import { useAi } from "@/lib/ai";
import { api, refreshAll, type Proposal } from "@/lib/api";
import { money, num, timeAgo } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const STATUS_VARIANT: Record<Proposal["status"], "gain" | "warn" | "muted" | "loss" | "secondary" | "default"> = {
  pending: "warn",
  idea: "secondary",
  executed: "gain",
  rejected: "muted",
  expired: "muted",
  blocked: "loss",
};

function useDecision(p: Proposal) {
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  async function approve() {
    setBusy("approve");
    try {
      await api.post(`/proposals/${p.id}/approve`);
      toast.success(`Bought ${p.symbol}`, { description: `Bracket order sent: stop ${money(p.stop)}, target ${money(p.target)}` });
      refreshAll();
    } catch (e) {
      toast.error(`Couldn't buy ${p.symbol}`, { description: e instanceof Error ? e.message : String(e) });
      refreshAll();
    } finally {
      setBusy(null);
    }
  }
  async function reject() {
    setBusy("reject");
    try {
      await api.post(`/proposals/${p.id}/reject`, { reason: "rejected by you" });
      toast(`Skipped ${p.symbol}`);
      refreshAll();
    } finally {
      setBusy(null);
    }
  }
  return { busy, approve, reject };
}

function PlanGrid({ p }: { p: Proposal }) {
  const { t } = useI18n();
  const rr = (p.target - p.entry) / Math.max(p.entry - p.stop, 1e-9);
  const items = [
    [t("entry"), money(p.entry)],
    [t("stop"), money(p.stop), "text-loss"],
    [t("target"), money(p.target), "text-gain"],
    [t("size"), p.qty ? `${p.qty} sh` : "—"],
    [t("risk"), p.risk_amount ? money(p.risk_amount, 0) : "—"],
    ["R:R", `${num(rr, 1)}x`],
  ];
  return (
    <div className="grid grid-cols-3 gap-x-4 gap-y-3">
      {items.map(([label, value, cls]) => (
        <div key={label}>
          <div className="text-muted-foreground text-[11px]">{label}</div>
          <div className={cn("tabular text-sm font-medium", cls)}>{value}</div>
        </div>
      ))}
    </div>
  );
}

export function ProposalCard({ p }: { p: Proposal }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const { busy, approve, reject } = useDecision(p);
  const actionable = p.status === "pending" || p.status === "idea";

  return (
    <>
      <Card className="gap-4 py-5 transition-colors hover:border-foreground/20">
        <div className="flex items-start gap-4 px-5">
          <ScoreRing score={p.score} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-lg font-semibold tracking-tight">{p.symbol}</span>
              <Badge variant={STATUS_VARIANT[p.status]}>{p.status === "pending" ? t("pendingApproval") : p.status}</Badge>
              <BacktestBadge bt={p.backtest} />
              {p.agent_source === "heuristic" && (
                <Badge variant="muted" className="gap-1">
                  <Bot /> heuristic
                </Badge>
              )}
            </div>
            <div className="text-muted-foreground truncate text-xs">
              {p.name} · {p.sector} · {timeAgo(p.created_at)}
            </div>
          </div>
        </div>
        <p className="line-clamp-3 px-5 text-sm leading-relaxed">{p.thesis}</p>
        <div className="space-y-3 px-5">
          <RangeBar stop={p.stop} entry={p.entry} target={p.target} />
          <PlanGrid p={p} />
        </div>
        <div className="bg-muted/40 mx-5 flex items-start gap-2 rounded-lg p-3 text-xs">
          <Swords className="text-warn mt-0.5 size-3.5 shrink-0" />
          <span className="text-muted-foreground line-clamp-2">
            <span className="text-foreground font-medium">Devil&apos;s advocate: </span>
            {p.devil.objection}
          </span>
        </div>
        {p.status_reason && !actionable && <p className="text-muted-foreground px-5 text-xs">{p.status_reason}</p>}
        <div className="flex items-center gap-2 px-5">
          <Button variant="ghost" size="sm" onClick={() => setOpen(true)}>
            Details
          </Button>
          {actionable && (
            <div className="ms-auto flex gap-2">
              <Button variant="outline" size="sm" disabled={!!busy} onClick={reject}>
                <X /> {t("reject")}
              </Button>
              {p.status === "pending" && (
                <Button size="sm" disabled={!!busy} onClick={approve}>
                  <Check /> {busy === "approve" ? "…" : t("approve")}
                </Button>
              )}
            </div>
          )}
        </div>
      </Card>
      <ProposalSheet p={p} open={open} onOpenChange={setOpen} />
    </>
  );
}

export function ProposalSheet({ p, open, onOpenChange }: { p: Proposal; open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t, lang } = useI18n();
  const { openAi } = useAi();
  const { busy, approve, reject } = useDecision(p);
  const actionable = p.status === "pending" || p.status === "idea";
  const heads = p.features.headlines ?? [];
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side={lang === "ar" ? "left" : "right"} className="overflow-y-auto">
        <SheetHeader className="border-b p-5">
          <div className="flex items-center gap-4">
            <ScoreRing score={p.score} size={56} />
            <div>
              <SheetTitle className="text-xl">
                {p.symbol} <span className="text-muted-foreground text-sm font-normal">{p.name}</span>
              </SheetTitle>
              <SheetDescription>
                {p.sector} · {timeAgo(p.created_at)} · by {p.agent_source === "claude" ? "Claude agents" : "heuristic agents"}
              </SheetDescription>
            </div>
          </div>
        </SheetHeader>

        <Tabs defaultValue="thesis" className="px-5">
          <TabsList className="w-full">
            <TabsTrigger value="thesis">{t("thesis")}</TabsTrigger>
            <TabsTrigger value="team">Team</TabsTrigger>
            <TabsTrigger value="backtest">Backtest</TabsTrigger>
            <TabsTrigger value="debate">{t("debate")}</TabsTrigger>
            <TabsTrigger value="safety">{t("safety")}</TabsTrigger>
          </TabsList>

          <TabsContent value="thesis" className="space-y-5 pt-3">
            <p className="text-sm leading-relaxed">{p.analyst.thesis}</p>
            <div className="grid gap-3">
              {[
                ["News", p.analyst.news_view],
                ["Chart", p.analyst.chart_view],
                ["Company", p.analyst.company_view],
              ].map(([k, v]) => (
                <div key={k} className="rounded-lg border p-3">
                  <div className="text-muted-foreground mb-1 text-[11px] font-medium uppercase tracking-wide">{k}</div>
                  <div className="text-sm">{v}</div>
                </div>
              ))}
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <div className="text-gain mb-2 text-xs font-medium">For</div>
                <ul className="space-y-1.5 text-sm">
                  {p.analyst.bullish_points.map((b) => (
                    <li key={b} className="flex gap-2">
                      <CheckCircle2 className="text-gain mt-0.5 size-3.5 shrink-0" /> {b}
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <div className="text-loss mb-2 text-xs font-medium">Risks</div>
                <ul className="space-y-1.5 text-sm">
                  {p.analyst.risks.map((b) => (
                    <li key={b} className="flex gap-2">
                      <XCircle className="text-loss mt-0.5 size-3.5 shrink-0" /> {b}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
            {heads.length > 0 && (
              <div>
                <div className="text-muted-foreground mb-2 text-xs font-medium">Headlines the agents read</div>
                <ul className="space-y-2">
                  {heads.map((h) => (
                    <li key={h.headline} className="flex items-start gap-2 text-sm">
                      <span className={cn("mt-1.5 size-1.5 shrink-0 rounded-full", (h.sentiment ?? 0) >= 0 ? "bg-gain" : "bg-loss")} />
                      <span>
                        {h.headline}{" "}
                        <span className="text-muted-foreground text-xs">
                          · {h.source} {h.official && "· official"} · {timeAgo(h.at)}
                        </span>
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </TabsContent>

          <TabsContent value="team" className="pt-1">
            <p className="text-muted-foreground pt-2 text-xs">What each specialist reported before the Analyst made its call.</p>
            <TeamReportsView team={p.team ?? {}} />
          </TabsContent>

          <TabsContent value="backtest" className="pt-3">
            {p.backtest?.verdict ? (
              <BacktestPanel bt={p.backtest} />
            ) : (
              <p className="text-muted-foreground text-xs">This idea was made before every trade was backtested.</p>
            )}
          </TabsContent>

          <TabsContent value="debate" className="space-y-4 pt-3">
            <Bubble who="Analyst" tone="gain" score={p.analyst.score}>
              {p.analyst.thesis}
            </Bubble>
            <Bubble who="Devil's advocate" tone="warn" score={`${p.devil.severity}/5`} scoreLabel="severity">
              {p.devil.objection}
              <div className="text-muted-foreground mt-2 text-xs">What would change my mind: {p.devil.what_would_change_my_mind}</div>
            </Bubble>
            <Bubble who="Manager" tone={p.manager.decision === "trade" ? "gain" : "loss"} score={p.manager.confidence} scoreLabel="confidence">
              <span className="font-medium">{p.manager.decision === "trade" ? "Take the trade. " : "Pass. "}</span>
              {p.manager.rebuttal}
              <div className="text-muted-foreground mt-2 text-xs">{p.manager.exit_plan}</div>
            </Bubble>
          </TabsContent>

          <TabsContent value="safety" className="space-y-4 pt-3">
            <div className="space-y-3 rounded-lg border p-4">
              <div className="text-sm font-medium">{t("plan")}</div>
              <RangeBar stop={p.stop} entry={p.entry} target={p.target} />
              <PlanGrid p={p} />
            </div>
            <div className="space-y-1.5">
              <div className="flex items-center gap-2 text-sm font-medium">
                <ShieldCheck className="text-primary size-4" /> Risk engine (plain code, final say)
              </div>
              {p.risk_checks.map((c) => (
                <div key={c.name} className="flex items-start gap-2 text-sm">
                  {c.passed ? <CheckCircle2 className="text-gain mt-0.5 size-4 shrink-0" /> : <XCircle className="text-loss mt-0.5 size-4 shrink-0" />}
                  <span className={cn(!c.passed && "text-loss")}>{c.detail}</span>
                </div>
              ))}
            </div>
          </TabsContent>
        </Tabs>

        <Separator className="mt-auto" />
        <div className="flex flex-wrap items-center gap-2 p-5 pt-0">
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              onOpenChange(false);
              openAi({ symbol: p.symbol, proposalId: p.id }, { prompt: lang === "ar" ? "لماذا اقترحت هذه الصفقة؟" : "Why did you propose this trade?" });
            }}
          >
            <Sparkles /> {t("askWhy")}
          </Button>
          {actionable && (
            <div className="ms-auto flex gap-2">
              <Button variant="outline" size="sm" disabled={!!busy} onClick={reject}>
                {t("reject")}
              </Button>
              {p.status === "pending" && (
                <Button size="sm" disabled={!!busy} onClick={approve}>
                  <Check /> {t("approve")}
                </Button>
              )}
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function Bubble({
  who,
  tone,
  score,
  scoreLabel = "score",
  children,
}: {
  who: string;
  tone: "gain" | "warn" | "loss";
  score: number | string;
  scoreLabel?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex gap-3">
      <div
        className={cn(
          "grid size-8 shrink-0 place-items-center rounded-full text-xs font-semibold",
          tone === "gain" && "bg-gain/15 text-gain",
          tone === "warn" && "bg-warn/15 text-warn",
          tone === "loss" && "bg-loss/15 text-loss",
        )}
      >
        {who[0]}
      </div>
      <div className="bg-muted/40 flex-1 rounded-md rounded-ss-sm p-3">
        <div className="mb-1 flex items-center justify-between text-xs">
          <span className="font-medium">{who}</span>
          <span className="text-muted-foreground tabular">
            {scoreLabel} {score}
          </span>
        </div>
        <div className="text-sm leading-relaxed">{children}</div>
      </div>
    </div>
  );
}
