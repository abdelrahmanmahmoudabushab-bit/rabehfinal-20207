from dataclasses import dataclass
from typing import Protocol


@dataclass
class Account:
    equity: float
    cash: float
    buying_power: float
    last_equity: float  # equity at the previous close, for today's P&L


@dataclass
class Position:
    symbol: str
    qty: int
    avg_price: float
    market_price: float

    @property
    def market_value(self) -> float:
        return self.qty * self.market_price

    @property
    def unrealized_pnl(self) -> float:
        return self.qty * (self.market_price - self.avg_price)


@dataclass
class OrderResult:
    ok: bool
    order_id: str | None
    fill_price: float | None
    message: str = ""


class Broker(Protocol):
    name: str

    def account(self) -> Account: ...
    def positions(self) -> list[Position]: ...
    def submit_bracket(self, symbol: str, qty: int, stop: float, target: float, ref_price: float) -> OrderResult: ...
    def update_stop(self, symbol: str, order_id: str | None, new_stop: float) -> bool: ...
    def close(self, symbol: str) -> OrderResult: ...
    def close_all(self) -> None: ...
    def sync_exits(self, open_trades: dict[str, str | None]) -> list[tuple[str, float, str]]:
        """Return (symbol, exit price, reason) for positions the broker closed on its own (stop/target legs)."""
        ...
