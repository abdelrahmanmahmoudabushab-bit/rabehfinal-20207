"""Paper broker for demo mode: fills at the simulated price and works stop/target legs every bar."""

import threading
import uuid
from dataclasses import dataclass

from ..market.base import MarketData
from .base import Account, OrderResult, Position

SLIPPAGE = 0.0003  # 3 bps against us on every fill


@dataclass
class _Pos:
    qty: int
    avg: float
    stop: float
    target: float
    order_id: str


class SimBroker:
    name = "paper-sim"

    def __init__(self, market: MarketData, starting_cash: float = 100_000.0):
        self.market = market
        self.cash = starting_cash
        self.last_equity = starting_cash
        self._pos: dict[str, _Pos] = {}
        self._exits: list[tuple[str, float, str]] = []
        self._lock = threading.RLock()

    def _price(self, symbol: str) -> float:
        q = self.market.quote(symbol)
        if not q:
            raise ValueError(f"no price for {symbol}")
        return q.price

    def account(self) -> Account:
        with self._lock:
            equity = self.cash + sum(p.qty * self._price(s) for s, p in self._pos.items())
        return Account(equity=equity, cash=self.cash, buying_power=self.cash, last_equity=self.last_equity)

    def positions(self) -> list[Position]:
        with self._lock:
            return [Position(s, p.qty, p.avg, self._price(s)) for s, p in self._pos.items()]

    def submit_bracket(self, symbol: str, qty: int, stop: float, target: float, ref_price: float,
                       limit_price: float | None = None) -> OrderResult:
        with self._lock:
            if symbol in self._pos:
                return OrderResult(False, None, None, "already holding this stock")
            fill = self._price(symbol) * (1 + SLIPPAGE)
            if limit_price is not None and fill > limit_price:
                return OrderResult(False, None, None, f"not filled: price {fill:.2f} is above the limit {limit_price:.2f}")
            if fill * qty > self.cash:
                return OrderResult(False, None, None, "not enough cash")
            oid = str(uuid.uuid4())
            self.cash -= fill * qty
            self._pos[symbol] = _Pos(qty, fill, stop, target, oid)
            return OrderResult(True, oid, fill, "filled")

    def update_stop(self, symbol: str, order_id: str | None, new_stop: float) -> bool:
        with self._lock:
            p = self._pos.get(symbol)
            if not p:
                return False
            p.stop = new_stop
            return True

    def close(self, symbol: str) -> OrderResult:
        with self._lock:
            p = self._pos.pop(symbol, None)
            if not p:
                return OrderResult(False, None, None, "no position")
            px = self._price(symbol) * (1 - SLIPPAGE)
            self.cash += px * p.qty
            return OrderResult(True, p.order_id, px, "closed")

    def close_all(self) -> None:
        for s in list(self._pos):
            self.close(s)

    def sync_exits(self, open_trades: dict[str, str | None] | None = None) -> list[tuple[str, float, str]]:
        """Work the bracket legs against the latest bar, like the broker would."""
        with self._lock:
            for sym, p in list(self._pos.items()):
                bars = self.market.minute_bars(sym, 1)
                if not bars:
                    continue
                b = bars[-1]
                if b.l <= p.stop:
                    self._fill_exit(sym, min(p.stop, b.o), "stop")
                elif b.h >= p.target:
                    self._fill_exit(sym, max(p.target, b.o) if b.o > p.target else p.target, "target")
            out, self._exits = self._exits, []
            return out

    def _fill_exit(self, sym: str, px: float, reason: str) -> None:
        p = self._pos.pop(sym)
        self.cash += px * p.qty
        self._exits.append((sym, px, reason))
