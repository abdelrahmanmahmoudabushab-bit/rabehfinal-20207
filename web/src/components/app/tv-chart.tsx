"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";

import type { Trade } from "@/lib/api";
import { cn } from "@/lib/utils";

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Indicators {
  ema9: boolean;
  ema21: boolean;
  vwap: boolean;
  volume: boolean;
  rsi: boolean;
}

// Canvas colors per theme (the chart library needs concrete colors, not CSS variables)
const PALETTE = {
  dark: { bg: "#000000", text: "#8c8c8c", grid: "#141414", border: "#262626", fg: "#f2f2f2", dim: "#5c5c5c", cross: "#7a7a7a", up: "#3ecf8e", down: "#f0616d" },
  light: { bg: "#ffffff", text: "#6b6b6b", grid: "#f2f2f2", border: "#e3e3e3", fg: "#111111", dim: "#a3a3a3", cross: "#8a8a8a", up: "#1a9e6a", down: "#d4424f" },
};

const ET_DAY = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" });

function ema(values: number[], n: number) {
  const k = 2 / (n + 1);
  const out: number[] = [];
  values.forEach((v, i) => out.push(i === 0 ? v : v * k + out[i - 1] * (1 - k)));
  return out;
}

function rsi(closes: number[], n = 14) {
  const out: (number | null)[] = closes.map(() => null);
  let gain = 0;
  let loss = 0;
  for (let i = 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    const g = Math.max(d, 0);
    const l = Math.max(-d, 0);
    if (i <= n) {
      gain += g / n;
      loss += l / n;
      if (i === n) out[i] = loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
    } else {
      gain = (gain * (n - 1) + g) / n;
      loss = (loss * (n - 1) + l) / n;
      out[i] = loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
    }
  }
  return out;
}

/** Session VWAP that resets each New York trading day. */
function vwap(bars: Candle[]) {
  let day = "";
  let pv = 0;
  let vol = 0;
  return bars.map((b) => {
    const d = ET_DAY.format(new Date(b.time * 1000));
    if (d !== day) {
      day = d;
      pv = 0;
      vol = 0;
    }
    pv += ((b.high + b.low + b.close) / 3) * b.volume;
    vol += b.volume;
    return vol ? pv / vol : b.close;
  });
}

function snapTime(bars: Candle[], iso: string): number | null {
  const t = Math.floor(new Date(iso).getTime() / 1000);
  let found: number | null = null;
  for (const b of bars) {
    if (b.time <= t) found = b.time;
    else break;
  }
  return found;
}

export interface Legend {
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
  chg: number;
}

export function TvChart({
  bars,
  trades,
  indicators,
  theme,
  colored,
  className,
  onLegend,
  levels,
}: {
  bars: Candle[];
  trades: Trade[];
  indicators: Indicators;
  theme: "dark" | "light";
  colored: boolean;
  className?: string;
  onLegend?: (l: Legend | null) => void;
  /** Planned entry/stop/target to draw when there is no open trade yet (deal finder). */
  levels?: { entry: number; stop: number; target: number };
}) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<{
    candles?: ISeriesApi<"Candlestick">;
    volume?: ISeriesApi<"Histogram">;
    ema9?: ISeriesApi<"Line">;
    ema21?: ISeriesApi<"Line">;
    vwap?: ISeriesApi<"Line">;
    rsi?: ISeriesApi<"Line">;
    markers?: ISeriesMarkersPluginApi<Time>;
    lines: IPriceLine[];
  }>({ lines: [] });
  const fitted = useRef(false);
  const lineLevels = useRef<number[]>([]); // entry/stop/target: the price scale always keeps these in view
  const [ready, setReady] = useState(0);
  const legendCb = useRef(onLegend);
  const barsRef = useRef(bars);
  // Latest props for the crosshair handler, which is registered once per chart
  useEffect(() => {
    legendCb.current = onLegend;
    barsRef.current = bars;
  }, [onLegend, bars]);

  const pal = PALETTE[theme];

  // Create the chart once per theme / color mode / pane layout
  useEffect(() => {
    if (!el.current) return;
    const c = createChart(el.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: pal.bg },
        textColor: pal.text,
        fontFamily: "var(--font-geist-mono), ui-monospace, monospace",
        fontSize: 11,
        panes: { separatorColor: pal.border, separatorHoverColor: pal.border },
        attributionLogo: false,
      },
      grid: { vertLines: { color: pal.grid }, horzLines: { color: pal.grid } },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: pal.cross, labelBackgroundColor: pal.fg === "#111111" ? "#111111" : "#2a2a2a", style: LineStyle.Dashed },
        horzLine: { color: pal.cross, labelBackgroundColor: pal.fg === "#111111" ? "#111111" : "#2a2a2a", style: LineStyle.Dashed },
      },
      rightPriceScale: { borderColor: pal.border, scaleMargins: { top: 0.08, bottom: indicators.volume ? 0.22 : 0.06 } },
      timeScale: { borderColor: pal.border, timeVisible: true, secondsVisible: false, rightOffset: 6 },
      localization: { priceFormatter: (p: number) => p.toFixed(2) },
    });
    const up = colored ? pal.up : pal.fg;
    const down = colored ? pal.down : pal.dim;
    const s: typeof series.current = { lines: [] };
    s.candles = c.addSeries(CandlestickSeries, {
      upColor: colored ? up : "rgba(0,0,0,0)",
      downColor: down,
      borderUpColor: up,
      borderDownColor: down,
      wickUpColor: up,
      wickDownColor: down,
      priceLineColor: pal.cross,
      autoscaleInfoProvider: (original: () => { priceRange: { minValue: number; maxValue: number } } | null) => {
        const res = original();
        const lv = lineLevels.current;
        if (!res || !lv.length) return res;
        return { ...res, priceRange: { minValue: Math.min(res.priceRange.minValue, ...lv), maxValue: Math.max(res.priceRange.maxValue, ...lv) } };
      },
    });
    if (indicators.volume) {
      s.volume = c.addSeries(HistogramSeries, { priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
      c.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    }
    const line = (color: string, width: 1 | 2, style = LineStyle.Solid) =>
      c.addSeries(LineSeries, { color, lineWidth: width, lineStyle: style, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
    if (indicators.ema9) s.ema9 = line(pal.fg, 1);
    if (indicators.ema21) s.ema21 = line(pal.dim, 2);
    if (indicators.vwap) s.vwap = line(colored ? "#e0a84b" : pal.cross, 1, LineStyle.Dashed);
    if (indicators.rsi) {
      s.rsi = c.addSeries(LineSeries, { color: pal.fg, lineWidth: 1, priceLineVisible: false, lastValueVisible: true }, 1);
      s.rsi.createPriceLine({ price: 70, color: pal.dim, lineStyle: LineStyle.Dotted, lineWidth: 1, axisLabelVisible: false, title: "" });
      s.rsi.createPriceLine({ price: 30, color: pal.dim, lineStyle: LineStyle.Dotted, lineWidth: 1, axisLabelVisible: false, title: "" });
      c.panes()[1]?.setHeight(110);
    }
    s.markers = createSeriesMarkers(s.candles, []);
    c.subscribeCrosshairMove((param) => {
      const d = param.seriesData.get(s.candles!) as { open: number; high: number; low: number; close: number } | undefined;
      if (!d || param.time == null) {
        legendCb.current?.(null);
        return;
      }
      const b = barsRef.current;
      const i = b.findIndex((x) => x.time === param.time);
      const prev = i > 0 ? b[i - 1].close : d.open;
      legendCb.current?.({ o: d.open, h: d.high, l: d.low, c: d.close, v: i >= 0 ? b[i].volume : 0, chg: ((d.close - prev) / prev) * 100 });
    });
    chart.current = c;
    series.current = s;
    fitted.current = false;
    setReady((n) => n + 1);
    return () => {
      c.remove();
      chart.current = null;
    };
  }, [theme, colored, indicators.volume, indicators.ema9, indicators.ema21, indicators.vwap, indicators.rsi, pal]);

  const derived = useMemo(() => {
    const closes = bars.map((b) => b.close);
    return { e9: ema(closes, 9), e21: ema(closes, 21), vw: vwap(bars), r: rsi(closes) };
  }, [bars]);

  // Push data whenever it changes; zoom is fitted once per chart (the parent remounts on symbol / timeframe change)
  useEffect(() => {
    const s = series.current;
    const c = chart.current;
    if (!c || !s.candles || !bars.length) return;
    const t = (x: number) => x as UTCTimestamp;
    s.candles.setData(bars.map((b) => ({ time: t(b.time), open: b.open, high: b.high, low: b.low, close: b.close })));
    s.volume?.setData(
      bars.map((b) => ({
        time: t(b.time),
        value: b.volume,
        color: b.close >= b.open ? (colored ? pal.up : pal.fg) + "55" : (colored ? pal.down : pal.dim) + "66",
      })),
    );
    s.ema9?.setData(bars.map((b, i) => ({ time: t(b.time), value: derived.e9[i] })));
    s.ema21?.setData(bars.map((b, i) => ({ time: t(b.time), value: derived.e21[i] })));
    s.vwap?.setData(bars.map((b, i) => ({ time: t(b.time), value: derived.vw[i] })));
    s.rsi?.setData(bars.flatMap((b, i) => (derived.r[i] == null ? [] : [{ time: t(b.time), value: derived.r[i] as number }])));

    // Our trades: buy/sell markers and the live position's entry, stop and target
    const markers: SeriesMarker<Time>[] = [];
    for (const tr of trades) {
      const et = snapTime(bars, tr.opened_at);
      if (et != null)
        markers.push({ time: t(et), position: "belowBar", shape: "arrowUp", color: colored ? pal.up : pal.fg, text: `BUY ${tr.qty}` });
      if (tr.closed_at && tr.exit_price != null) {
        const xt = snapTime(bars, tr.closed_at);
        if (xt != null)
          markers.push({
            time: t(xt),
            position: "aboveBar",
            shape: "arrowDown",
            color: (tr.pnl ?? 0) >= 0 ? pal.up : pal.down,
            text: `SELL ${(tr.pnl ?? 0) >= 0 ? "+" : ""}${(tr.pnl ?? 0).toFixed(0)}`,
          });
      }
    }
    markers.sort((a, b) => Number(a.time) - Number(b.time));
    s.markers?.setMarkers(markers);

    s.lines.forEach((l) => s.candles!.removePriceLine(l));
    s.lines = [];
    const open = trades.find((tr) => !tr.closed_at) ?? (levels ? { entry_price: levels.entry, stop: levels.stop, target: levels.target } : undefined);
    lineLevels.current = open ? [open.entry_price, open.stop, open.target] : [];
    if (open) {
      s.lines.push(
        s.candles.createPriceLine({ price: open.entry_price, color: pal.cross, lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: true, title: "ENTRY" }),
        s.candles.createPriceLine({ price: open.stop, color: pal.down, lineStyle: LineStyle.Solid, lineWidth: 1, axisLabelVisible: true, title: "STOP" }),
        s.candles.createPriceLine({ price: open.target, color: pal.up, lineStyle: LineStyle.Solid, lineWidth: 1, axisLabelVisible: true, title: "TARGET" }),
      );
    }

    if (!fitted.current) {
      c.timeScale().fitContent();
      fitted.current = true;
    }
  }, [bars, trades, derived, ready, colored, pal, levels]);

  return <div ref={el} className={cn("h-full w-full", className)} />;
}
