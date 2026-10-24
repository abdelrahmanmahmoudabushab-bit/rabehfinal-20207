"use client";

import { useState } from "react";
import { ChevronDown, ListChecks } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { Empty, PageHeader } from "@/components/app/bits";
import { useApi, type LogRow } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const STAGES: { key: string; label: string }[] = [
  { key: "", label: "All decisions" },
  { key: "data_check", label: "1 · Data" },
  { key: "laya", label: "2 · LAYA" },
  { key: "halal", label: "3 · Halal" },
  { key: "score", label: "4 · Score" },
  { key: "devils_advocate", label: "5 · Devil" },
  { key: "risk", label: "6 · Risk" },
  { key: "user", label: "7 · You" },
  { key: "execution", label: "Bought" },
  { key: "exit", label: "Exits" },
];

const OUTCOME: Record<LogRow["outcome"], "loss" | "gain" | "muted" | "warn"> = { no: "loss", yes: "gain", info: "muted", alert: "warn" };

export default function LogPage() {
  const { t } = useI18n();
  const [stage, setStage] = useState("");
  const { data } = useApi<LogRow[]>(`/log?limit=200${stage ? `&stage=${stage}` : "&exclude=laya"}`);
  return (
    <>
      <PageHeader
        title={t("log")}
        description="Every trade must pass seven checks. Every “no” is written down here with its reason, so nothing the agents do is a black box."
      />
      <div className="mb-3 flex flex-wrap gap-1.5">
        {STAGES.map((s) => (
          <Button key={s.key} size="sm" variant={stage === s.key ? "secondary" : "ghost"} onClick={() => setStage(s.key)}>
            {s.label}
          </Button>
        ))}
      </div>
      <Card className="py-2">
        <CardContent className="divide-y px-2">
          {!data ? (
            <Skeleton className="m-2 h-60" />
          ) : !data.length ? (
            <div className="p-4">
              <Empty icon={<ListChecks />}>Nothing logged for this step yet.</Empty>
            </div>
          ) : (
            data.map((r) => <Row key={r.id} r={r} />)
          )}
        </CardContent>
      </Card>
    </>
  );
}

function Row({ r }: { r: LogRow }) {
  const [open, setOpen] = useState(false);
  const hasDetail = Object.keys(r.detail ?? {}).length > 0;
  const isLaya = r.stage === "laya";
  return (
    <div className="px-2 py-3">
      <button
        className={cn("flex w-full items-start gap-3 text-start", hasDetail && "cursor-pointer")}
        onClick={() => hasDetail && setOpen(!open)}
      >
        <Badge variant={OUTCOME[r.outcome]} className="mt-0.5 w-12">
          {r.outcome}
        </Badge>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            {r.symbol && <span className="font-semibold">{r.symbol}</span>}
            <span className="text-muted-foreground text-xs">{r.stage.replace("_", " ")}</span>
          </div>
          <div className={cn("text-sm", !open && "line-clamp-2")}>{r.reason}</div>
        </div>
        <span className="text-muted-foreground shrink-0 text-xs">{dateTime(r.at)}</span>
        {hasDetail && <ChevronDown className={cn("text-muted-foreground mt-0.5 size-4 shrink-0 transition-transform", open && "rotate-180")} />}
      </button>
      {open && hasDetail && (
        <div className="bg-muted/40 ms-15 mt-2 rounded-lg p-3 text-xs">
          {isLaya ? (
            <ul className="grid gap-1 sm:grid-cols-2">
              {Object.entries(r.detail as Record<string, string[]>).map(([sym, reasons]) => (
                <li key={sym}>
                  <span className="font-medium">{sym}</span> <span className="text-muted-foreground">{reasons.join(", ")}</span>
                </li>
              ))}
            </ul>
          ) : (
            <pre className="overflow-x-auto font-mono whitespace-pre-wrap">{JSON.stringify(r.detail, null, 2)}</pre>
          )}
        </div>
      )}
    </div>
  );
}
