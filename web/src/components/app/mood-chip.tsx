"use client";

import Link from "next/link";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/misc";
import { useApi, type Mood, type PrecomputeStatus } from "@/lib/api";
import { clock } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export const MOOD_STYLE: Record<Mood["level"], string> = {
  calm: "border-foreground/40 text-foreground",
  careful: "border-warn text-warn",
  stormy: "border-loss text-loss bg-loss/10",
};

export function MoodChip() {
  const { data: m } = useApi<Mood>("/mood", { refreshInterval: 15000 });
  const { t } = useI18n();
  const { data: pc } = useApi<PrecomputeStatus>("/backtest/precompute", { refreshInterval: 60000 });
  if (!m?.level) return null;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Link
          href="/agents#mood"
          className={cn("hidden items-center gap-1.5 rounded-sm border px-1.5 py-0.5 font-mono text-[10px] uppercase sm:flex", MOOD_STYLE[m.level])}
        >
          <span className="size-1.5 rounded-full bg-current" />
          {m.level}
          {m.vix != null && <span className="text-muted-foreground hidden xl:inline">VIX {m.vix.toFixed(1)}</span>}
        </Link>
      </TooltipTrigger>
      <TooltipContent className="max-w-sm">
        <div className="font-semibold">Market mood: {m.level}</div>
        <div>{m.summary}</div>
        <div className="mt-1 opacity-80">{m.reasons.join(" · ")}</div>
        {pc?.regime && (
          <div className="mt-1 font-mono text-[10px] uppercase opacity-80">
            {t("marketRegime")}: {t(pc.regime)}
          </div>
        )}
        {m.next_event && (
          <div className="mt-1 opacity-80">
            Next: {m.next_event.event} at {clock(m.next_event.time)} ({m.next_event.impact})
          </div>
        )}
      </TooltipContent>
    </Tooltip>
  );
}
