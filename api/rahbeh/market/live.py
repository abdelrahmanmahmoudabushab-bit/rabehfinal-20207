"""Live market data: Alpaca (prices, minute bars, news), Finnhub (second price source),
Financial Modeling Prep (fundamentals). Everything degrades gracefully when a key is missing."""

import logging
import threading
import time
from datetime import UTC, datetime, timedelta

import httpx
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import NewsClient, StockHistoricalDataClient
from alpaca.data.requests import NewsRequest, StockBarsRequest, StockLatestTradeRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient

from ..config import Settings
from .base import Bar, Fundamentals, NewsItem, Quote
from .universe import BENCHMARK, FUNDAMENTALS, SYMBOLS

log = logging.getLogger(__name__)


class LiveMarket:
    name = "alpaca"

    def __init__(self, s: Settings):
        self.s = s
        self._data = StockHistoricalDataClient(s.alpaca_api_key, s.alpaca_secret_key)
        self._news = NewsClient(s.alpaca_api_key, s.alpaca_secret_key)
        self._trading = TradingClient(s.alpaca_api_key, s.alpaca_secret_key, paper=s.alpaca_paper)
        self._feed = DataFeed.SIP if s.alpaca_data_feed.lower() == "sip" else DataFeed.IEX
        self._symbols = [x.strip().upper() for x in s.watchlist.split(",") if x.strip()] or list(SYMBOLS)
        self._lock = threading.RLock()
        self._bars: dict[str, list[Bar]] = {}
        self._daily: dict[str, tuple[float, list[Bar]]] = {}
        self._quotes: dict[str, Quote] = {}
        self._news_cache: tuple[float, list[NewsItem]] = (0.0, [])
        self._fund_cache: dict[str, tuple[float, Fundamentals | None]] = {}
        self._clock_cache: tuple[float, bool] = (0.0, False)
        self._http = httpx.Client(timeout=10)

    def refresh(self) -> None:
        """Pull the latest minute bars and trades for the whole watchlist in two requests."""
        syms = [*self._symbols, BENCHMARK]
        start = datetime.now(UTC) - timedelta(hours=6)
        try:
            barset = self._data.get_stock_bars(StockBarsRequest(
                symbol_or_symbols=syms, timeframe=TimeFrame.Minute, start=start,
                feed=self._feed, adjustment=Adjustment.ALL,
            ))
            trades = self._data.get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols=syms, feed=self._feed))
        except Exception as e:  # network / auth problems surface as stale data downstream
            log.warning("alpaca refresh failed: %s", e)
            return
        with self._lock:
            for sym, rows in barset.data.items():
                self._bars[sym] = [Bar(r.timestamp, r.open, r.high, r.low, r.close, r.volume) for r in rows][-400:]
            for sym, t in trades.items():
                self._quotes[sym] = Quote(sym, float(t.price), t.timestamp, "alpaca")

    def now(self) -> datetime:
        return datetime.now(UTC)

    def is_open(self) -> bool:
        ts, is_open = self._clock_cache
        if time.time() - ts > 60:
            try:
                is_open = bool(self._trading.get_clock().is_open)
            except Exception as e:
                log.warning("clock failed: %s", e)
            self._clock_cache = (time.time(), is_open)
        return is_open

    def universe(self) -> list[str]:
        return list(self._symbols)

    def minute_bars(self, symbol: str, limit: int = 120) -> list[Bar]:
        with self._lock:
            return list(self._bars.get(symbol, [])[-limit:])

    def daily_bars(self, symbol: str, limit: int = 60) -> list[Bar]:
        cached = self._daily.get(symbol)
        if cached and time.time() - cached[0] < 6 * 3600:
            return cached[1][-limit:]
        try:
            bs = self._data.get_stock_bars(StockBarsRequest(
                symbol_or_symbols=symbol, timeframe=TimeFrame.Day,
                start=datetime.now(UTC) - timedelta(days=int(limit * 1.6) + 10),
                feed=self._feed, adjustment=Adjustment.ALL,
            ))
            rows = [Bar(r.timestamp, r.open, r.high, r.low, r.close, r.volume) for r in bs.data.get(symbol, [])]
        except Exception as e:
            log.warning("daily bars failed for %s: %s", symbol, e)
            rows = cached[1] if cached else []
        self._daily[symbol] = (time.time(), rows)
        return rows[-limit:]

    def quote(self, symbol: str) -> Quote | None:
        with self._lock:
            return self._quotes.get(symbol)

    def second_quote(self, symbol: str) -> Quote | None:
        if not self.s.finnhub_api_key:
            return None
        try:
            r = self._http.get("https://finnhub.io/api/v1/quote", params={"symbol": symbol, "token": self.s.finnhub_api_key})
            r.raise_for_status()
            d = r.json()
            if not d.get("c"):
                return None
            return Quote(symbol, float(d["c"]), datetime.fromtimestamp(d.get("t") or time.time(), UTC), "finnhub")
        except Exception as e:
            log.warning("finnhub quote failed for %s: %s", symbol, e)
            return None

    def news(self, symbols: list[str] | None = None, limit: int = 50) -> list[NewsItem]:
        ts, items = self._news_cache
        if time.time() - ts > 60:
            try:
                res = self._news.get_news(NewsRequest(symbols=",".join(self._symbols), limit=50))
                raw = res.data.get("news", []) if hasattr(res, "data") else res.get("news", [])
                items = [
                    NewsItem(
                        id=str(n.id), headline=n.headline, source=n.source or "alpaca",
                        published_at=n.created_at, symbols=list(n.symbols or []), url=n.url or "",
                        official="press release" in (n.source or "").lower(),
                    )
                    for n in raw
                ]
            except Exception as e:
                log.warning("news fetch failed: %s", e)
            self._news_cache = (time.time(), items)
        if symbols:
            items = [n for n in items if not n.symbols or set(n.symbols) & set(symbols)]
        return items[:limit]

    def fundamentals(self, symbol: str) -> Fundamentals | None:
        cached = self._fund_cache.get(symbol)
        if cached and time.time() - cached[0] < 12 * 3600:
            return cached[1]
        f = self._fmp(symbol) if self.s.fmp_api_key else None
        f = f or FUNDAMENTALS.get(symbol)
        self._fund_cache[symbol] = (time.time(), f)
        return f

    def _fmp(self, symbol: str) -> Fundamentals | None:
        base, key = "https://financialmodelingprep.com/stable", self.s.fmp_api_key

        def get(path: str) -> dict:
            r = self._http.get(f"{base}/{path}", params={"symbol": symbol, "apikey": key, "limit": 1})
            r.raise_for_status()
            rows = r.json()
            return rows[0] if rows else {}

        try:
            p, inc, bal = get("profile"), get("income-statement"), get("balance-sheet-statement")
        except Exception as e:
            log.warning("fmp failed for %s: %s", symbol, e)
            return None
        known = FUNDAMENTALS.get(symbol)
        return Fundamentals(
            symbol=symbol, name=p.get("companyName", symbol), sector=p.get("sector", "Unknown"),
            industry=p.get("industry", ""), market_cap=float(p.get("marketCap") or 0),
            revenue=float(inc.get("revenue") or 0), net_income=float(inc.get("netIncome") or 0),
            total_debt=float(bal.get("totalDebt") or 0), cash=float(bal.get("cashAndCashEquivalents") or 0),
            business_tags=known.business_tags if known else [],
        )
