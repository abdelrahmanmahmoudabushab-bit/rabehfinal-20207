"use client";

import { useState } from "react";
import { OctagonX, Play } from "lucide-react";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { api, refreshAll } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export function KillSwitch({ on }: { on: boolean }) {
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);

  async function set(next: boolean) {
    setBusy(true);
    try {
      await api.post("/kill", { on: next });
      toast[next ? "error" : "success"](next ? t("killOn") : t("resume"));
      refreshAll();
    } catch (e) {
      toast.error(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (on) {
    return (
      <Button size="sm" variant="outline" disabled={busy} onClick={() => set(false)}>
        <Play /> {t("resume")}
      </Button>
    );
  }

  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button size="sm" variant="outline" disabled={busy} className="border-loss/60 text-loss hover:bg-loss hover:text-white">
          <OctagonX /> <span className="hidden sm:inline">{t("killSwitch")}</span>
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t("killConfirmTitle")}</AlertDialogTitle>
          <AlertDialogDescription>{t("killConfirmBody")}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{t("cancel")}</AlertDialogCancel>
          <AlertDialogAction variant="destructive" onClick={() => set(true)}>
            {t("killConfirm")}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
