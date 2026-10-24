"use client";

import { createContext, useCallback, useContext, useEffect, useSyncExternalStore } from "react";

export type Lang = "en" | "ar";

const en = {
  dashboard: "Dashboard",
  ideas: "Trade ideas",
  trades: "Trades",
  market: "Market",
  coach: "Coach",
  log: "Decision log",
  review: "Reviewer",
  settings: "Settings",
  equity: "Account value",
  today: "Today",
  vsSp500: "vs S&P 500",
  winRate: "Win rate",
  openPositions: "Open positions",
  noPositions: "No open positions. The agents are watching the market.",
  killSwitch: "Kill switch",
  killOn: "Trading stopped",
  killConfirmTitle: "Stop all trading now?",
  killConfirmBody: "This closes every open position at market price, cancels pending ideas, and blocks new trades until you turn it back on.",
  killConfirm: "Stop everything",
  resume: "Resume trading",
  cancel: "Cancel",
  approve: "Approve & buy",
  reject: "Reject",
  scanNow: "Scan now",
  pendingApproval: "waiting for you",
  briefing: "Daily briefing",
  thesis: "Thesis",
  debate: "Agents' debate",
  plan: "Trade plan",
  safety: "Safety checks",
  askWhy: "Ask why",
  entry: "Entry",
  stop: "Stop",
  target: "Target",
  size: "Size",
  risk: "Risk",
  score: "Score",
  demo: "Demo market",
  live: "Live",
  paper: "Paper",
  marketOpen: "Market open",
  marketClosed: "Market closed",
  mode_research: "Research",
  mode_copilot: "Copilot",
  mode_autopilot: "Autopilot",
  noIdeas: "No open ideas right now. New ones appear as the scanner finds them.",
  performance: "Performance vs S&P 500",
  alerts: "Alerts",
  close: "Close",
  ask: "Ask",
  askPlaceholder: "Ask about any stock or trade… e.g. “Why did you buy NVDA?”",
  save: "Save",
};

const ar: typeof en = {
  dashboard: "لوحة التحكم",
  ideas: "أفكار التداول",
  trades: "الصفقات",
  market: "السوق",
  coach: "المدرب",
  log: "سجل القرارات",
  review: "المراجع",
  settings: "الإعدادات",
  equity: "قيمة الحساب",
  today: "اليوم",
  vsSp500: "مقابل S&P 500",
  winRate: "نسبة الربح",
  openPositions: "المراكز المفتوحة",
  noPositions: "لا توجد مراكز مفتوحة. الوكلاء يراقبون السوق.",
  killSwitch: "زر الإيقاف",
  killOn: "التداول متوقف",
  killConfirmTitle: "إيقاف كل التداول الآن؟",
  killConfirmBody: "سيتم إغلاق كل المراكز المفتوحة بسعر السوق، وإلغاء الأفكار المعلقة، ومنع أي صفقات جديدة حتى تعيد التشغيل.",
  killConfirm: "أوقف كل شيء",
  resume: "استئناف التداول",
  cancel: "إلغاء",
  approve: "موافقة وشراء",
  reject: "رفض",
  scanNow: "افحص الآن",
  pendingApproval: "بانتظار موافقتك",
  briefing: "الملخص اليومي",
  thesis: "الفكرة",
  debate: "نقاش الوكلاء",
  plan: "خطة الصفقة",
  safety: "فحوصات الأمان",
  askWhy: "اسأل لماذا",
  entry: "الدخول",
  stop: "وقف الخسارة",
  target: "الهدف",
  size: "الكمية",
  risk: "المخاطرة",
  score: "التقييم",
  demo: "سوق تجريبي",
  live: "مباشر",
  paper: "تجريبي",
  marketOpen: "السوق مفتوح",
  marketClosed: "السوق مغلق",
  mode_research: "مساعد بحث",
  mode_copilot: "مساعد طيار",
  mode_autopilot: "طيار آلي",
  noIdeas: "لا توجد أفكار حاليًا. ستظهر الأفكار الجديدة عندما يجدها الماسح.",
  performance: "الأداء مقابل S&P 500",
  alerts: "التنبيهات",
  close: "إغلاق",
  ask: "اسأل",
  askPlaceholder: "اسأل عن أي سهم أو صفقة… مثلاً: «لماذا اشتريت NVDA؟»",
  save: "حفظ",
};

export type Key = keyof typeof en;
const dict = { en, ar };

const Ctx = createContext<{ lang: Lang; setLang: (l: Lang) => void; t: (k: Key) => string }>({
  lang: "en",
  setLang: () => {},
  t: (k) => en[k],
});

const LANG_KEY = "rahbeh.lang";
const listeners = new Set<() => void>();

function readLang(): Lang {
  try {
    return localStorage.getItem(LANG_KEY) === "ar" ? "ar" : "en";
  } catch {
    return "en";
  }
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

export function I18nProvider({ children }: { children: React.ReactNode }) {
  // The language lives in localStorage; the server render always uses English.
  const lang = useSyncExternalStore(subscribe, readLang, () => "en" as Lang);

  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
  }, [lang]);

  const setLang = useCallback((l: Lang) => {
    try {
      localStorage.setItem(LANG_KEY, l);
    } catch {}
    listeners.forEach((cb) => cb());
  }, []);

  const t = useCallback((k: Key) => dict[lang][k] ?? en[k], [lang]);
  return <Ctx.Provider value={{ lang, setLang, t }}>{children}</Ctx.Provider>;
}

export const useI18n = () => useContext(Ctx);
