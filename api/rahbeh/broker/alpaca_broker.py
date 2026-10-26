"""Alpaca broker (paper by default). Orders are brackets: entry + stop-loss + take-profit, held at the broker
so the protection stays in place even if Rahbeh goes offline."""

import logging
import time

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import (
    OrderClass,
    OrderSide,
    OrderStatus,
    OrderType,
    QueryOrderStatus,
    TimeInForce,
)
from alpaca.trading.requests import (
    GetOrderByIdRequest,
    GetOrdersRequest,
    LimitOrderRequest,
    MarketOrderRequest,
    ReplaceOrderRequest,
    StopLossRequest,
    TakeProfitRequest,
)

from ..config import Settings
from .base import Account, OrderResult, Position

log = logging.getLogger(__name__)


class AlpacaBroker:
    def __init__(self, s: Settings):
        self.client = TradingClient(s.alpaca_api_key, s.alpaca_secret_key, paper=s.alpaca_paper)
        self.name = "alpaca-paper" if s.alpaca_paper else "alpaca-live"

    def account(self) -> Account:
        a = self.client.get_account()
        return Account(float(a.equity), float(a.cash), float(a.buying_power), float(a.last_equity),
                       int(a.daytrade_count or 0), bool(a.pattern_day_trader))

    def positions(self) -> list[Position]:
        return [
            Position(p.symbol, int(float(p.qty)), float(p.avg_entry_price), float(p.current_price or p.avg_entry_price))
            for p in self.client.get_all_positions()
        ]

    def submit_bracket(self, symbol: str, qty: int, stop: float, target: float, ref_price: float,
                       limit_price: float | None = None) -> OrderResult:
        common = dict(symbol=symbol, qty=qty, side=OrderSide.BUY, time_in_force=TimeInForce.DAY, order_class=OrderClass.BRACKET,
                      take_profit=TakeProfitRequest(limit_price=round(target, 2)), stop_loss=StopLossRequest(stop_price=round(stop, 2)))
        try:
            req = (LimitOrderRequest(limit_price=round(limit_price, 2), **common) if limit_price is not None
                   else MarketOrderRequest(**common))
            order = self.client.submit_order(req)
        except Exception as e:
            return OrderResult(False, None, None, f"broker rejected: {e}")
        fill = None
        for _ in range(10):  # marketable orders usually fill within a second or two
            o = self.client.get_order_by_id(order.id)
            if o.status == OrderStatus.FILLED and o.filled_avg_price:
                fill = float(o.filled_avg_price)
                break
            time.sleep(0.5)
        if fill is None and limit_price is not None:
            # price ran away from the limit: don't chase, cancel the whole bracket
            try:
                self.client.cancel_order_by_id(order.id)
            except Exception as e:
                log.warning("cancel failed for %s: %s", symbol, e)
            return OrderResult(False, str(order.id), None, f"not filled at or below the limit {limit_price:.2f}; order cancelled")
        return OrderResult(True, str(order.id), fill or ref_price, "filled" if fill else "submitted")

    def _stop_leg(self, order_id: str):
        parent = self.client.get_order_by_id(order_id, GetOrderByIdRequest(nested=True))
        for leg in parent.legs or []:
            if leg.order_type in (OrderType.STOP, OrderType.STOP_LIMIT) and leg.status not in (
                OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.EXPIRED,
            ):
                return leg
        return None

    def update_stop(self, symbol: str, order_id: str | None, new_stop: float) -> bool:
        if not order_id:
            return False
        try:
            leg = self._stop_leg(order_id)
            if not leg:
                return False
            self.client.replace_order_by_id(leg.id, ReplaceOrderRequest(stop_price=round(new_stop, 2)))
            return True
        except Exception as e:
            log.warning("stop update failed for %s: %s", symbol, e)
            return False

    def close(self, symbol: str) -> OrderResult:
        try:
            # bracket legs reserve the shares, so cancel them before closing
            for o in self.client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])):
                self.client.cancel_order_by_id(o.id)
            o = self.client.close_position(symbol)
            fill = None
            for _ in range(10):
                o = self.client.get_order_by_id(o.id)
                if o.status == OrderStatus.FILLED and o.filled_avg_price:
                    fill = float(o.filled_avg_price)
                    break
                time.sleep(0.5)
            return OrderResult(True, str(o.id), fill, "closed")
        except Exception as e:
            return OrderResult(False, None, None, f"close failed: {e}")

    def close_all(self) -> None:
        self.client.close_all_positions(cancel_orders=True)

    def sync_exits(self, open_trades: dict[str, str | None]) -> list[tuple[str, float, str]]:
        held = {p.symbol for p in self.positions()}
        out = []
        for sym, order_id in open_trades.items():
            if sym in held or not order_id:
                continue
            reason, px = "broker", None
            try:
                parent = self.client.get_order_by_id(order_id, GetOrderByIdRequest(nested=True))
                for leg in parent.legs or []:
                    if leg.status == OrderStatus.FILLED and leg.filled_avg_price:
                        px = float(leg.filled_avg_price)
                        reason = "target" if leg.order_type == OrderType.LIMIT else "stop"
            except Exception as e:
                log.warning("exit sync failed for %s: %s", sym, e)
            if px is not None:
                out.append((sym, px, reason))
        return out
