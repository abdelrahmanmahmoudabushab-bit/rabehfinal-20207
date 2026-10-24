"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUp, CheckCircle2, Loader2, Send, Sparkles, X, XCircle } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { TeamReportsView } from "@/components/app/team";
import { api, refreshAll, useApi, type Analysis, type MarketRow } from "@/lib/api";
import { useAi } from "@/lib/ai";
import { money } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type Msg = { role: "user"; text: string } | { role: "ai"; text: string } | { role: "analysis"; data: Analysis };

const QUICK = {
  en: (s?: string) =>
    s
      ? [`Is ${s} a buy right now?`, `Explain the ${s} chart in plain words`, `What are the biggest risks in ${s}?`, `Where would you put the stop on ${s}?`]
      : ["What's moving the market today?", "Explain my open positions", "What is VWAP and why does it matter?", "How does the risk engine protect me?"],
  ar: (s?: string) =>
    s
      ? [`هل ${s} فرصة شراء الآن؟`, `اشرح رسم ${s} بكلمات بسيطة`, `ما أكبر المخاطر في ${s}؟`, `أين تضع وقف الخسارة على ${s}؟`]
      : ["ما الذي يحرك السوق اليوم؟", "اشرح مراكزي المفتوحة", "ما هو VWAP ولماذا يهم؟", "كيف يحميني محرك المخاطر؟"],
};

export function AiButton({ className, compact }: { className?: string; compact?: boolean }) {
  const { openAi, ctx } = useAi();
  return (
    <Button size="sm" className={cn("gap-1.5 font-semibold", className)} onClick={() => openAi(ctx)}>
      <Sparkles /> AI
      {!compact && <kbd className="bg-primary-foreground/15 hidden rounded-sm px-1 font-mono text-[10px] md:inline">⌘K</kbd>}
    </Button>
  );
}

export function AiPanel() {
  const { open, setOpen, ctx, setCtx, seed, nonce } = useAi();
  const { lang } = useI18n();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const { data: market } = useApi<MarketRow[]>(open ? "/market" : null, { refreshInterval: 0 });
  const end = useRef<HTMLDivElement>(null);
  const handled = useRef(0);
  const symbol = ctx.symbol;

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [msgs, busy]);

  async function ask(q: string) {
    const text = q.trim();
    if (!text || busy) return;
    setMsgs((m) => [...m, { role: "user", text }]);
    setInput("");
    setBusy(true);
    try {
      const r = await api.post<{ answer: string }>("/ask", { question: text, symbol, proposal_id: ctx.proposalId, lang });
      setMsgs((m) => [...m, { role: "ai", text: r.answer }]);
    } catch (e) {
      setMsgs((m) => [...m, { role: "ai", text: `Sorry — ${e instanceof Error ? e.message : String(e)}` }]);
    } finally {
      setBusy(false);
    }
  }

  async function analyze(sym = symbol) {
    if (!sym || busy) return;
    setMsgs((m) => [...m, { role: "user", text: `Run the full agent team on ${sym}` }]);
    setBusy(true);
    try {
      const data = await api.post<Analysis>(`/analyze/${sym}`);
      setMsgs((m) => [...m, { role: "analysis", data }]);
    } catch (e) {
      setMsgs((m) => [...m, { role: "ai", text: `Analysis failed — ${e instanceof Error ? e.message : String(e)}` }]);
    } finally {
      setBusy(false);
    }
  }

  // Run whatever the opener asked for (e.g. "Analyze with AI" from the chart toolbar)
  useEffect(() => {
    if (!open || !seed || handled.current === nonce) return;
    handled.current = nonce;
    if (seed.action === "analyze") void analyze(ctx.symbol);
    else if (seed.prompt) void ask(seed.prompt);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, nonce]);

  if (!open) return null;

  return (
    <aside className="bg-background fixed inset-y-0 end-0 z-50 flex w-full flex-col border-s shadow-2xl sm:w-[420px]">
      <header className="flex h-12 items-center gap-2 border-b px-3">
        <span className="bg-primary text-primary-foreground grid size-6 place-items-center rounded-sm">
          <Sparkles className="size-3.5" />
        </span>
        <span className="text-sm font-semibold">Rahbeh AI</span>
        <Select value={symbol ?? "none"} onValueChange={(v) => setCtx({ symbol: v === "none" ? undefined : v })}>
          <SelectTrigger size="sm" className="ms-2 h-7 w-32 font-mono text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="none">General</SelectItem>
            {market?.map((m) => (
              <SelectItem key={m.symbol} value={m.symbol} className="font-mono text-xs">
                {m.symbol}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {ctx.proposalId && <Badge variant="outline">idea #{ctx.proposalId}</Badge>}
        <Button variant="ghost" size="icon-sm" className="ms-auto" onClick={() => setOpen(false)} aria-label="Close AI">
          <X />
        </Button>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {msgs.length === 0 && (
          <div className="space-y-4 pt-4">
            <div>
              <div className="text-lg font-semibold tracking-tight">{symbol ? `Ask about ${symbol}` : "Ask anything"}</div>
              <p className="text-muted-foreground text-sm">
                The AI reads the same live prices, indicators, news and company data the agents use. Education, not advice.
              </p>
            </div>
            {symbol && (
              <button
                onClick={() => analyze()}
                className="hover:bg-accent flex w-full items-center gap-3 rounded-md border p-3 text-start transition-colors"
              >
                <Sparkles className="size-4 shrink-0" />
                <div>
                  <div className="text-sm font-medium">Analyze {symbol} with the agent team</div>
                  <div className="text-muted-foreground text-xs">Analyst → Devil&apos;s advocate → Manager → Risk engine. Nothing is bought.</div>
                </div>
              </button>
            )}
            <div className="grid gap-1.5">
              {QUICK[lang](symbol).map((q) => (
                <button key={q} onClick={() => ask(q)} className="hover:bg-accent rounded-md border px-3 py-2 text-start text-sm transition-colors">
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {msgs.map((m, i) =>
          m.role === "analysis" ? (
            <AnalysisCard key={i} a={m.data} />
          ) : (
            <div key={i} className={cn("flex", m.role === "user" && "justify-end")}>
              <div
                className={cn(
                  "max-w-[88%] rounded-md px-3 py-2 text-sm leading-relaxed whitespace-pre-line",
                  m.role === "user" ? "bg-primary text-primary-foreground" : "bg-muted",
                )}
              >
                {m.text}
              </div>
            </div>
          ),
        )}
        {busy && (
          <div className="text-muted-foreground flex items-center gap-2 text-sm">
            <Loader2 className="size-4 animate-spin" /> Thinking…
          </div>
        )}
        <div ref={end} />
      </div>

      <form
        className="flex items-end gap-2 border-t p-3"
        onSubmit={(e) => {
          e.preventDefault();
          void ask(input);
        }}
      >
        <Textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void ask(input);
            }
          }}
          rows={1}
          placeholder={symbol ? `Ask about ${symbol}…` : "Ask about any stock or trade…"}
          className="max-h-36 min-h-9 resize-none rounded-md"
        />
        <Button type="submit" size="icon" disabled={busy || !input.trim()} aria-label="Send">
          <ArrowUp />
        </Button>
      </form>
    </aside>
  );
}

function AnalysisCard({ a }: { a: Analysis }) {
  const [sent, setSent] = useState<number | null>(a.proposal_id);
  const [busy, setBusy] = useState(false);
  const go = a.verdict === "trade";

  async function propose() {
    setBusy(true);
    try {
      const r = await api.post<Analysis>(`/analyze/${a.symbol}?propose=true`);
      if (r.proposal_id) {
        setSent(r.proposal_id);
        toast.success(`${a.symbol} sent to Trade ideas`, { description: "Approve it there to buy." });
        refreshAll();
      } else toast.error("No longer passes every check");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="overflow-hidden rounded-md border">
      <div className={cn("flex items-center justify-between px-3 py-2", go ? "bg-gain/10" : "bg-muted")}>
        <div className="font-mono text-sm font-semibold">{a.symbol}</div>
        <div className={cn("text-xs font-semibold tracking-wide uppercase", go ? "text-gain" : "text-muted-foreground")}>
          {go ? "Trade" : "No trade"} · score {a.analyst.score}
        </div>
      </div>
      <div className="space-y-3 p-3 text-sm">
        <p className="leading-relaxed">{a.analyst.thesis}</p>
        {a.team && (
          <details className="rounded-sm border px-2">
            <summary className="cursor-pointer py-1.5 text-xs font-medium">Specialist reports (news, chart, company, mood)</summary>
            <TeamReportsView team={a.team} compact />
          </details>
        )}
        <div className="bg-muted/50 rounded-sm p-2 text-xs">
          <span className="font-medium">Devil&apos;s advocate ({a.devil.severity}/5): </span>
          {a.devil.objection}
        </div>
        <div className="text-xs">
          <span className="font-medium">Manager: </span>
          {a.manager.rebuttal}
        </div>
        <div className="grid grid-cols-4 gap-2 border-y py-2 font-mono text-xs">
          <div>
            <div className="text-muted-foreground">Entry</div>
            {money(a.plan.entry)}
          </div>
          <div>
            <div className="text-muted-foreground">Stop</div>
            <span className="text-loss">{money(a.plan.stop)}</span>
          </div>
          <div>
            <div className="text-muted-foreground">Target</div>
            <span className="text-gain">{money(a.plan.target)}</span>
          </div>
          <div>
            <div className="text-muted-foreground">Size</div>
            {a.plan.qty || "—"}
          </div>
        </div>
        <ul className="space-y-1">
          {a.gates.map((g) => (
            <li key={g.name} className="flex items-start gap-2 text-xs">
              {g.passed ? <CheckCircle2 className="text-gain mt-px size-3.5 shrink-0" /> : <XCircle className="text-loss mt-px size-3.5 shrink-0" />}
              <span>
                <span className="font-medium">{g.name}</span> <span className="text-muted-foreground">— {g.detail}</span>
              </span>
            </li>
          ))}
        </ul>
        {go &&
          (sent ? (
            <div className="text-muted-foreground text-xs">Sent to Trade ideas as #{sent}.</div>
          ) : (
            <Button size="sm" className="w-full" disabled={busy} onClick={propose}>
              <Send /> Send to Trade ideas
            </Button>
          ))}
        <div className="text-muted-foreground text-[11px]">by {a.source === "claude" ? "Claude agents" : "rule-based agents (add an Anthropic key for Claude)"}</div>
      </div>
    </div>
  );
}
