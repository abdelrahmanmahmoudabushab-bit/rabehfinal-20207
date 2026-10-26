"use client";

import { Sparkles } from "lucide-react";

import { Skeleton } from "@/components/ui/misc";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Empty, PageHeader } from "@/components/app/bits";
import { ProposalCard } from "@/components/app/proposal";
import { useApi, type Proposal, type Settings } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

const MODE_HELP: Record<"copilot" | "autopilot", string> = {
  copilot: "Copilot mode: every trade waits for your one-tap approval. Ideas expire after 15 minutes because prices move.",
  autopilot: "Autopilot mode: approved ideas are executed automatically, inside your limits. You can still pull the kill switch any time.",
};

export default function IdeasPage() {
  const { t } = useI18n();
  const { data: open } = useApi<Proposal[]>("/proposals?status=open");
  const { data: all } = useApi<Proposal[]>("/proposals?status=all&limit=60", { refreshInterval: 15000 });
  const { data: settings } = useApi<Settings>("/settings", { refreshInterval: 0 });
  const history = all?.filter((p) => p.status !== "pending" && p.status !== "idea");

  return (
    <>
      <PageHeader title={t("ideas")} description={settings ? (settings.mode === "research" ? t("researchHelp") : MODE_HELP[settings.mode]) : undefined} />
      <Tabs defaultValue="open">
        <TabsList>
          <TabsTrigger value="open">Open {open?.length ? `(${open.length})` : ""}</TabsTrigger>
          <TabsTrigger value="history">History</TabsTrigger>
        </TabsList>
        <TabsContent value="open" className="pt-3">
          <Grid items={open} empty={t("noIdeas")} />
        </TabsContent>
        <TabsContent value="history" className="pt-3">
          <Grid items={history} empty="No past ideas yet." />
        </TabsContent>
      </Tabs>
    </>
  );
}

function Grid({ items, empty }: { items?: Proposal[]; empty: string }) {
  if (!items)
    return (
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-80 rounded-md" />
        ))}
      </div>
    );
  if (!items.length) return <Empty icon={<Sparkles />}>{empty}</Empty>;
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {items.map((p) => (
        <ProposalCard key={p.id} p={p} />
      ))}
    </div>
  );
}
