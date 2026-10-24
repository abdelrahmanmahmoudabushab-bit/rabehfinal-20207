"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ArrowUp, Bot, User } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { PageHeader } from "@/components/app/bits";
import { api, useApi, type MarketRow } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

interface Msg {
  role: "user" | "coach";
  text: string;
  symbol?: string;
}

const SUGGESTIONS = {
  en: ["Is this stock moving on news or just heavy trading?", "What are the biggest risks right now?", "Explain RSI and VWAP for this stock in simple words"],
  ar: ["هل يتحرك هذا السهم بسبب خبر أم بسبب تداول كثيف؟", "ما أكبر المخاطر الآن؟", "اشرح مؤشر RSI و VWAP لهذا السهم بكلمات بسيطة"],
};

export default function CoachPage() {
  return (
    <Suspense>
      <Coach />
    </Suspense>
  );
}

function Coach() {
  const { t, lang } = useI18n();
  const params = useSearchParams();
  const proposalId = params.get("proposal");
  const [symbol, setSymbol] = useState(params.get("symbol") ?? "none");
  const [input, setInput] = useState(proposalId ? (lang === "ar" ? "لماذا اقترحت هذه الصفقة؟" : "Why did you propose this trade?") : "");
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [busy, setBusy] = useState(false);
  const { data: market } = useApi<MarketRow[]>("/market", { refreshInterval: 0 });
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [msgs, busy]);

  async function send(text = input) {
    const q = text.trim();
    if (!q || busy) return;
    const sym = symbol === "none" ? undefined : symbol;
    setMsgs((m) => [...m, { role: "user", text: q, symbol: sym }]);
    setInput("");
    setBusy(true);
    try {
      const r = await api.post<{ answer: string }>("/ask", {
        question: q,
        symbol: sym,
        proposal_id: proposalId ? Number(proposalId) : undefined,
        lang,
      });
      setMsgs((m) => [...m, { role: "coach", text: r.answer }]);
    } catch (e) {
      setMsgs((m) => [...m, { role: "coach", text: `Sorry — ${e instanceof Error ? e.message : String(e)}` }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title={t("coach")} description="Ask about any stock or any trade in plain English or Arabic. The Coach only uses the live data the agents see." />
      <Card className="flex h-[calc(100dvh-14rem)] min-h-[28rem] flex-col gap-0 py-0">
        <div className="flex items-center gap-2 border-b p-3">
          <span className="text-muted-foreground text-xs">Stock</span>
          <Select value={symbol} onValueChange={setSymbol}>
            <SelectTrigger size="sm" className="w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">Any / general</SelectItem>
              {market?.map((m) => (
                <SelectItem key={m.symbol} value={m.symbol}>
                  {m.symbol} · {m.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {proposalId && <Badge variant="secondary">about idea #{proposalId}</Badge>}
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          {msgs.length === 0 && (
            <div className="mx-auto flex max-w-md flex-col items-center gap-4 py-10 text-center">
              <div className="bg-primary/15 text-primary grid size-12 place-items-center rounded-full">
                <Bot className="size-6" />
              </div>
              <p className="text-muted-foreground text-sm">Pick a stock (optional) and ask a question.</p>
              <div className="flex flex-wrap justify-center gap-2">
                {SUGGESTIONS[lang].map((s) => (
                  <Button key={s} variant="outline" size="sm" className="h-auto py-1.5 whitespace-normal" onClick={() => send(s)}>
                    {s}
                  </Button>
                ))}
              </div>
            </div>
          )}
          {msgs.map((m, i) => (
            <div key={i} className={cn("flex gap-3", m.role === "user" && "flex-row-reverse")}>
              <div
                className={cn(
                  "grid size-8 shrink-0 place-items-center rounded-full",
                  m.role === "user" ? "bg-secondary" : "bg-primary/15 text-primary",
                )}
              >
                {m.role === "user" ? <User className="size-4" /> : <Bot className="size-4" />}
              </div>
              <div
                className={cn(
                  "max-w-[80%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-line",
                  m.role === "user" ? "bg-primary text-primary-foreground rounded-se-sm" : "bg-muted rounded-ss-sm",
                )}
              >
                {m.symbol && <div className="mb-0.5 text-[11px] opacity-70">{m.symbol}</div>}
                {m.text}
              </div>
            </div>
          ))}
          {busy && (
            <div className="flex gap-3">
              <div className="bg-primary/15 text-primary grid size-8 place-items-center rounded-full">
                <Bot className="size-4" />
              </div>
              <div className="bg-muted flex items-center gap-1 rounded-2xl px-4 py-3">
                {[0, 1, 2].map((d) => (
                  <span key={d} className="bg-muted-foreground size-1.5 animate-bounce rounded-full" style={{ animationDelay: `${d * 120}ms` }} />
                ))}
              </div>
            </div>
          )}
          <div ref={end} />
        </div>

        <form
          className="flex items-end gap-2 border-t p-3"
          onSubmit={(e) => {
            e.preventDefault();
            send();
          }}
        >
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder={t("askPlaceholder")}
            className="max-h-40 min-h-10 resize-none"
            rows={1}
          />
          <Button type="submit" size="icon" disabled={busy || !input.trim()} aria-label={t("ask")}>
            <ArrowUp />
          </Button>
        </form>
      </Card>
    </>
  );
}
