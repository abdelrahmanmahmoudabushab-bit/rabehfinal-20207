"use client";

import { useState } from "react";
import { Bot, Check, Hand, Lock, Plane, Plug, Save, Search } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress, Skeleton, Slider } from "@/components/ui/misc";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { PageHeader } from "@/components/app/bits";
import { api, refreshAll, useApi, type Mode, type Settings, type Status } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const MODES: { id: Mode; icon: React.ComponentType<{ className?: string }>; title: string; body: string; who: string }[] = [
  { id: "research", icon: Search, title: "Research assistant", body: "Scan, explain, alert, answer questions.", who: "You trade in your own app" },
  { id: "copilot", icon: Hand, title: "Copilot", body: "A full trade (entry, size, stop, target) waits for your one tap.", who: "You press buy" },
  { id: "autopilot", icon: Plane, title: "Autopilot", body: "Trades on its own, only inside your rules below.", who: "The agents press buy" },
];

type Draft = Omit<Settings, "autopilot" | "hard_caps" | "kill_switch">;

function toDraft(s: Settings): Draft {
  return {
    mode: s.mode, risk_per_trade_pct: s.risk_per_trade_pct, daily_loss_limit_pct: s.daily_loss_limit_pct,
    max_position_pct: s.max_position_pct, max_sector_pct: s.max_sector_pct, max_open_positions: s.max_open_positions,
    max_trades_per_day: s.max_trades_per_day, min_reward_risk: s.min_reward_risk, score_threshold: s.score_threshold,
    halal_only: s.halal_only, allowed_symbols: s.allowed_symbols, strategy: s.strategy, language: s.language,
  };
}

export default function SettingsPage() {
  const { data } = useApi<Settings>("/settings", { refreshInterval: 0 });
  if (!data) return <Skeleton className="h-96 rounded-md" />;
  return <SettingsForm data={data} />;
}

function SettingsForm({ data }: { data: Settings }) {
  const { t, lang, setLang } = useI18n();
  const { data: status } = useApi<Status>("/status");
  const [d, setD] = useState<Draft>(() => toDraft(data));
  const [symbols, setSymbols] = useState(data.allowed_symbols.join(", "));
  const [saving, setSaving] = useState(false);

  const caps = data.hard_caps;
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setD({ ...d, [k]: v });

  async function save(overrides: Partial<Draft> = {}) {
    setSaving(true);
    try {
      const body = { ...d, ...overrides, allowed_symbols: symbols.split(/[,\s]+/).filter(Boolean) };
      setD(toDraft(await api.put<Settings>("/settings", body)));
      toast.success("Settings saved");
      refreshAll();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  const sliders: { k: keyof Draft; label: string; help: string; min: number; max: number; step: number; unit: string }[] = [
    { k: "risk_per_trade_pct", label: "Risk per trade", help: "Most you can lose on one trade if the stop is hit.", min: 0.1, max: caps.risk_per_trade_pct, step: 0.05, unit: "%" },
    { k: "daily_loss_limit_pct", label: "Daily loss stop", help: "Trading pauses for the rest of the day past this loss.", min: 0.5, max: caps.daily_loss_limit_pct, step: 0.25, unit: "%" },
    { k: "max_position_pct", label: "Max per stock", help: "Largest share of your account in one stock.", min: 2, max: caps.max_position_pct, step: 1, unit: "%" },
    { k: "max_sector_pct", label: "Max per sector", help: "Keeps you from loading up on one industry.", min: 10, max: caps.max_sector_pct, step: 5, unit: "%" },
    { k: "max_open_positions", label: "Open positions", help: "Most trades open at the same time.", min: 1, max: caps.max_open_positions, step: 1, unit: "" },
    { k: "max_trades_per_day", label: "Trades per day", help: "Stops over-trading.", min: 1, max: 20, step: 1, unit: "" },
    { k: "min_reward_risk", label: "Min reward / risk", help: "Target must be at least this many times the risk.", min: caps.min_reward_risk, max: 4, step: 0.1, unit: "x" },
    { k: "score_threshold", label: "Score line", help: "Analyst score needed before the devil's advocate even looks.", min: 50, max: 95, step: 1, unit: "" },
  ];

  return (
    <>
      <PageHeader title={t("settings")} description="You set the limits; the plain-code risk engine enforces them. Hard caps can never be raised, by you or by the AI.">
        <Button onClick={() => save()} disabled={saving}>
          <Save /> {t("save")}
        </Button>
      </PageHeader>

      <div className="grid gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Mode</CardTitle>
            <CardDescription>Unlocked in order, so trust is earned before money moves on its own.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-3">
            {MODES.map((m) => {
              const locked = m.id === "autopilot" && !data.autopilot.unlocked;
              const active = d.mode === m.id;
              return (
                <button
                  key={m.id}
                  disabled={locked}
                  onClick={() => {
                    set("mode", m.id);
                    save({ mode: m.id });
                  }}
                  className={cn(
                    "relative flex flex-col gap-2 rounded-md border p-4 text-start transition-colors",
                    active ? "border-primary bg-primary/5 ring-primary/30 ring-2" : "hover:border-foreground/20",
                    locked ? "cursor-not-allowed opacity-60" : "cursor-pointer",
                  )}
                >
                  <div className="flex items-center gap-2">
                    <m.icon className={cn("size-4", active && "text-primary")} />
                    <span className="font-medium">{m.title}</span>
                    {active && <Check className="text-primary ms-auto size-4" />}
                    {locked && <Lock className="ms-auto size-4" />}
                  </div>
                  <p className="text-muted-foreground text-sm">{m.body}</p>
                  <Badge variant="muted">{m.who}</Badge>
                  {locked && (
                    <div className="mt-1 space-y-1">
                      <Progress value={(data.autopilot.copilot_trades / data.autopilot.needed) * 100} />
                      <div className="text-muted-foreground text-[11px]">
                        {data.autopilot.copilot_trades}/{data.autopilot.needed} Copilot trades completed to unlock
                      </div>
                    </div>
                  )}
                </button>
              );
            })}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Risk limits</CardTitle>
            <CardDescription>Hard caps shown on the right of each slider.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-x-10 gap-y-7 md:grid-cols-2">
            {sliders.map((s) => (
              <div key={s.k} className="space-y-3">
                <div className="flex items-baseline justify-between">
                  <Label>{s.label}</Label>
                  <span className="tabular text-sm font-semibold">
                    {String(d[s.k])}
                    {s.unit}
                  </span>
                </div>
                <Slider
                  min={s.min}
                  max={s.max}
                  step={s.step}
                  value={[Number(d[s.k])]}
                  onValueChange={([v]) => set(s.k, Number(v.toFixed(2)) as never)}
                />
                <div className="text-muted-foreground flex justify-between text-xs">
                  <span>{s.help}</span>
                  <span className="shrink-0 ps-2">
                    max {s.max}
                    {s.unit}
                  </span>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>

        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Strategy &amp; screens</CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <Label>Halal only</Label>
                  <p className="text-muted-foreground mt-1 text-xs">Screens out banks, insurance, alcohol, tobacco, gambling, weapons, and companies with debt or cash over 30% of market value.</p>
                </div>
                <Switch checked={d.halal_only} onCheckedChange={(v) => set("halal_only", v)} />
              </div>
              <div className="space-y-2">
                <Label>Strategy</Label>
                <Select value={d.strategy} onValueChange={(v) => set("strategy", v)}>
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="day_momentum">Day trader — momentum &amp; news</SelectItem>
                    <SelectItem value="swing">Swing trader</SelectItem>
                    <SelectItem value="long_term">Long-term investor</SelectItem>
                    <SelectItem value="dividend">Dividend focus</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-muted-foreground text-xs">Shared with the agents as your preference. The MVP trades intraday only.</p>
              </div>
              <div className="space-y-2">
                <Label>Allowed stocks</Label>
                <Input value={symbols} onChange={(e) => setSymbols(e.target.value.toUpperCase())} placeholder="Empty = any stock the scanner watches" />
                <p className="text-muted-foreground text-xs">Comma separated, e.g. AAPL, MSFT, NVDA.</p>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Language &amp; connections</CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="flex items-center justify-between">
                <Label>Language</Label>
                <Select value={lang} onValueChange={(v) => setLang(v as "en" | "ar")}>
                  <SelectTrigger className="w-36">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="en">English</SelectItem>
                    <SelectItem value="ar">العربية</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-3">
                <Conn icon={Plug} label="Market data" value={status?.market_source} ok={!status?.demo} hint="Set ALPACA_API_KEY / ALPACA_SECRET_KEY" />
                <Conn icon={Plug} label="Broker" value={status?.broker} ok={!status?.demo} hint="Alpaca paper trading by default" />
                <Conn icon={Bot} label="AI agents" value={status?.claude ? status.model ?? "" : "heuristic"} ok={status?.claude} hint="Set ANTHROPIC_API_KEY" />
              </div>
              <p className="text-muted-foreground text-xs">Keys live only in the server&apos;s environment (api/.env), never in the browser.</p>
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}

function Conn({ icon: Icon, label, value, ok, hint }: { icon: React.ComponentType<{ className?: string }>; label: string; value?: string; ok?: boolean; hint: string }) {
  return (
    <div className="flex items-center gap-3 rounded-lg border p-3">
      <Icon className="text-muted-foreground size-4" />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium">{label}</div>
        <div className="text-muted-foreground truncate text-xs">{ok ? value : `${value ?? "…"} — ${hint}`}</div>
      </div>
      <span className={cn("size-2 rounded-full", ok ? "bg-gain" : "bg-warn")} />
    </div>
  );
}
