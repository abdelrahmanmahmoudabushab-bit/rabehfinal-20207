"use client";

import { createContext, useCallback, useContext, useEffect, useSyncExternalStore } from "react";

export type Lang = "en" | "ar";

const en = {
  chart: "Chart",
  deals: "Deals",
  lab: "Lab",
  portfolio: "Portfolio",
  agents: "Agents",
  dashboard: "Dashboard",
  ideas: "Ideas",
  trades: "Trades",
  market: "Market",
  coach: "Coach",
  log: "Log",
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
  killConfirmBody: "Closes all open positions and cancels pending ideas. Blocks new trades until you resume. If a close fails, you are alerted.",
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
  agentsValue: "Agents: cost and value",
  agentsValueDesc: "What each agent costs, and whether its opinion predicts better trades.",
  agentCol: "Agent",
  callsCol: "Calls",
  errorsCol: "Errors",
  costCol: "Cost",
  avgMsCol: "Avg ms",
  blockedBy: "Blocked by stage",
  byAnalystScore: "Avg R by analyst score",
  byDevilSeverity: "Avg R by devil severity",
  tradesCol: "trades",
  noClosedTrades: "No closed trades yet, so there is nothing to judge the agents on.",
  setupHealth: "Setup health",
  setupHealthDesc: "Live results of each setup over 30 days against what its backtest promised.",
  noLiveTrades: "No live trades yet",
  statusOk: "ok",
  statusCut: "size halved",
  statusPaused: "paused",
  liveR: "live",
  expectedR: "expected",
  marketRegime: "Market regime",
  regimeNow: "now",
  regimeUnknown: "unknown",
  trending: "trending",
  choppy: "choppy",
  selectionBar: "Selection bar",
  selectionLine: "Picked from {n} variants; out-of-sample t-stat {t} needed {bar}",
  nightlyPrecompute: "Nightly precompute",
  nightlyPrecomputeDesc: "Tests every stock and setup after the close so intraday verdicts are instant.",
  runNow: "Run now",
  precomputeStarted: "Precompute started",
  statusCol: "Status",
  progressCol: "Progress",
  cachedVerdicts: "Cached verdicts",
  idle: "idle",
  running: "running",
  done: "done",
  failed: "failed",
  scheduledNightly: "scheduled nightly",
  notScheduled: "not scheduled",
  cacheSaved: "Cache saved",
  loadFailed: "Could not load",
  researchHelp: "Research mode: the agents explain ideas and never buy on their own; Approve is disabled here. On the Deals page your own explicit “buy N shares” click still works in every mode (the risk engine and kill switch still apply).",
  logDesc: "Every trade goes through the scan pipeline: data check, scores, LAYA, halal, Analyst, Devil/Manager, backtest, risk engine, earnings and mood checks. Every “no” is written down here with its reason, so nothing the agents do is a black box.",
  portfolioDesc: "Stops and targets are held at the broker. Untested trades move the stop to breakeven at +1R and trail it after +2R; tested trades use their tested rule. Live day trading closes everything by 15:50 ET; swing holds overnight, and the demo market uses a 2-hour time stop.",
  halalNote: "Screens banks, insurance, alcohol, tobacco, gambling, weapons/defense, adult and pork businesses, and debt or cash over 30% of market value. Business tags come from a built-in table for the 28 built-in stocks and a keyword match on the industry for any other symbol. Live mode without FMP_API_KEY uses built-in illustrative debt/cash figures, not live filings.",
  strategyNote: "Day trader closes everything by 15:50 ET in live mode; Swing holds overnight. Long-only.",
  autopilotUnlockNote: "Only Copilot trades opened by the app count. Trades closed by a restart or outside the app don't, and demo (simulated) trades never count toward the live threshold (5 in demo, 20 live).",
  declaredSkills: "Declared skills",
};

const ar: typeof en = {
  chart: "الرسم البياني",
  deals: "صائد الصفقات",
  lab: "مختبر الاستراتيجيات",
  portfolio: "المحفظة",
  agents: "الوكلاء",
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
  killConfirmBody: "يغلق كل المراكز المفتوحة ويلغي الأفكار المعلقة، ويمنع أي صفقات جديدة حتى تستأنف. إذا فشل إغلاق أي مركز فسيصلك تنبيه.",
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
  agentsValue: "الوكلاء: التكلفة والقيمة",
  agentsValueDesc: "كم يكلف كل وكيل، وهل رأيه يتنبأ بصفقات أفضل.",
  agentCol: "الوكيل",
  callsCol: "الطلبات",
  errorsCol: "الأخطاء",
  costCol: "التكلفة",
  avgMsCol: "متوسط ms",
  blockedBy: "المحظور حسب المرحلة",
  byAnalystScore: "متوسط R حسب تقييم المحلل",
  byDevilSeverity: "متوسط R حسب شدة محامي الشيطان",
  tradesCol: "صفقات",
  noClosedTrades: "لا توجد صفقات مغلقة بعد، فلا يوجد ما نحكم به على الوكلاء.",
  setupHealth: "صحة الاستراتيجيات",
  setupHealthDesc: "النتائج الحية لكل استراتيجية خلال 30 يومًا مقابل ما وعد به اختبارها الخلفي.",
  noLiveTrades: "لا توجد صفقات حية بعد",
  statusOk: "سليمة",
  statusCut: "الحجم مخفض للنصف",
  statusPaused: "متوقفة",
  liveR: "فعلي",
  expectedR: "متوقع",
  marketRegime: "نمط السوق",
  regimeNow: "الآن",
  regimeUnknown: "غير معروف",
  trending: "اتجاهي",
  choppy: "متذبذب",
  selectionBar: "حاجز الاختيار",
  selectionLine: "اختيرت من {n} نسخة؛ إحصائية t خارج العينة {t} والمطلوب {bar}",
  nightlyPrecompute: "الحساب المسبق الليلي",
  nightlyPrecomputeDesc: "يختبر كل سهم واستراتيجية بعد الإغلاق لتكون أحكام اليوم فورية.",
  runNow: "شغّل الآن",
  precomputeStarted: "بدأ الحساب المسبق",
  statusCol: "الحالة",
  progressCol: "التقدم",
  cachedVerdicts: "أحكام محفوظة",
  idle: "خامل",
  running: "قيد العمل",
  done: "اكتمل",
  failed: "فشل",
  scheduledNightly: "مجدول ليليًا",
  notScheduled: "غير مجدول",
  cacheSaved: "وفرته الذاكرة المؤقتة",
  loadFailed: "تعذر التحميل",
  researchHelp: "وضع البحث: الوكلاء يشرحون الأفكار ولا يشترون من تلقاء أنفسهم، وزر الموافقة معطّل هنا. في صفحة الصفقات يعمل ضغطك الصريح على «اشترِ N سهم» في كل الأوضاع (ويبقى محرك المخاطر وزر الإيقاف ساريين).",
  logDesc: "كل صفقة تمر بخط الفحص: فحص البيانات، التقييمات، LAYA، الشرعية، المحلل، محامي الشيطان والمدير، الاختبار الخلفي، محرك المخاطر، وفحوص الأرباح والمزاج. كل «لا» تُسجَّل هنا مع سببها، فلا شيء مما يفعله الوكلاء صندوق أسود.",
  portfolioDesc: "وقف الخسارة والهدف محفوظان عند الوسيط. الصفقات غير المختبرة ترفع الوقف إلى نقطة التعادل عند +1R وتلحقه بعد +2R؛ والمختبرة تستخدم قاعدتها المختبرة. التداول اليومي المباشر يغلق كل شيء قبل 15:50 بتوقيت نيويورك؛ والسوينغ يحتفظ بالمراكز طوال الليل، والسوق التجريبي يغلق بعد ساعتين.",
  halalNote: "يستبعد البنوك والتأمين والكحول والتبغ والقمار والسلاح والدفاع والترفيه للبالغين ولحم الخنزير، والديون أو النقد التي تتجاوز 30% من القيمة السوقية. تصنيف النشاط من جدول مدمج للأسهم الـ28 المدمجة ومطابقة كلمات في اسم الصناعة لأي رمز آخر. في الوضع المباشر بدون FMP_API_KEY تُستخدم أرقام دين ونقد توضيحية مدمجة وليست من البيانات الحية.",
  strategyNote: "المتداول اليومي يغلق كل شيء قبل 15:50 في الوضع المباشر؛ والسوينغ يحتفظ بالمراكز طوال الليل. شراء فقط بدون بيع على المكشوف.",
  autopilotUnlockNote: "تُحتسب فقط صفقات المساعد الطيار التي فتحها التطبيق. الصفقات التي أُغلقت بإعادة تشغيل أو خارج التطبيق لا تُحتسب، والصفقات التجريبية لا تُحتسب أبدًا نحو الحد المباشر (5 في التجريبي، 20 في المباشر).",
  declaredSkills: "المهارات المعلنة",
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
