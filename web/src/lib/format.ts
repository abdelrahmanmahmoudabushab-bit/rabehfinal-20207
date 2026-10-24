export const money = (n: number | null | undefined, digits = 2) =>
  n == null ? "—" : n.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: digits, maximumFractionDigits: digits });

export const signedMoney = (n: number | null | undefined) => (n == null ? "—" : `${n >= 0 ? "+" : "−"}${money(Math.abs(n))}`);

export const pct = (n: number | null | undefined, digits = 2) => (n == null ? "—" : `${n >= 0 ? "+" : ""}${n.toFixed(digits)}%`);

export const num = (n: number | null | undefined, digits = 2) => (n == null ? "—" : n.toFixed(digits));

export const tone = (n: number | null | undefined) => (n == null || n === 0 ? "text-muted-foreground" : n > 0 ? "text-gain" : "text-loss");

export function timeAgo(iso: string | null | undefined) {
  if (!iso) return "—";
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 0) return "just now";
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export const clock = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—";

export const dateTime = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";
