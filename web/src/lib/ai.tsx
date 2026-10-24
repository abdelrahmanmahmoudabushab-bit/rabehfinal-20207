"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

export interface AiContext {
  symbol?: string;
  proposalId?: number;
}

export interface AiSeed {
  prompt?: string;
  action?: "analyze";
}

interface AiApi {
  open: boolean;
  ctx: AiContext;
  seed: AiSeed | null;
  nonce: number;
  openAi: (ctx?: AiContext, seed?: AiSeed) => void;
  setOpen: (o: boolean) => void;
  setCtx: (ctx: AiContext) => void;
}

const Ctx = createContext<AiApi | null>(null);

export function AiProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const [ctx, setCtxState] = useState<AiContext>({});
  const [seed, setSeed] = useState<AiSeed | null>(null);
  const [nonce, setNonce] = useState(0);

  const openAi = useCallback((c?: AiContext, s?: AiSeed) => {
    if (c) setCtxState((prev) => ({ ...prev, ...c }));
    setSeed(s ?? null);
    setNonce((n) => n + 1);
    setOpen(true);
  }, []);

  const setCtx = useCallback((c: AiContext) => setCtxState(c), []);

  // ⌘K / Ctrl+K toggles the assistant from anywhere
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const value = useMemo(() => ({ open, ctx, seed, nonce, openAi, setOpen, setCtx }), [open, ctx, seed, nonce, openAi, setCtx]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAi() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAi outside AiProvider");
  return v;
}
