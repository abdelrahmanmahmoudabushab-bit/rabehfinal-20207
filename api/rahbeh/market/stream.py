"""Live trade stream from Alpaca's websocket. Prices arrive the moment they print instead of once per scan, and a
sharp move wakes the scanner immediately. REST polling keeps running underneath as the fallback, so a dropped
connection only costs speed."""

import logging
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import UTC, datetime

log = logging.getLogger(__name__)


class PriceTape:
    """Remembers the last minute of prints per stock and says when one moved sharply (pure logic, no network)."""

    def __init__(self, move_pct: float = 1.0, window_s: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self.move_pct, self.window_s, self.clock = move_pct, window_s, clock
        self._prints: dict[str, deque] = defaultdict(deque)
        self.last: dict[str, tuple[float, float]] = {}  # symbol -> (price, monotonic time)

    def update(self, symbol: str, price: float) -> bool:
        """Record a print. True when the price is now at least `move_pct` away from where it was `window_s` ago."""
        now = self.clock()
        d = self._prints[symbol]
        d.append((now, price))
        while d and now - d[0][0] > self.window_s:
            d.popleft()
        self.last[symbol] = (price, now)
        base = d[0][1]
        return len(d) > 1 and base > 0 and abs(price / base - 1) * 100 >= self.move_pct

    def fresh_price(self, symbol: str, max_age_s: float = 10.0) -> float | None:
        hit = self.last.get(symbol)
        return hit[0] if hit and self.clock() - hit[1] <= max_age_s else None


class PriceStream:
    def __init__(self, api_key: str, secret: str, symbols: list[str], feed, on_price: Callable[[str, float, datetime], None],
                 on_move: Callable[[str], None] | None = None, move_pct: float = 1.0):
        self.api_key, self.secret, self.symbols, self.feed = api_key, secret, symbols, feed
        self.on_price, self.on_move = on_price, on_move
        self.tape = PriceTape(move_pct)
        self.connected = False
        self.prints = 0
        self._stop = threading.Event()
        self._cooldown: dict[str, float] = {}

    def start(self) -> None:
        threading.Thread(target=self._loop, daemon=True, name="price-stream").start()

    def stop(self) -> None:
        self._stop.set()

    def _handle(self, symbol: str, price: float, ts: datetime | None) -> None:
        self.prints += 1
        hot = self.tape.update(symbol, price)
        self.on_price(symbol, price, ts or datetime.now(UTC))
        if hot and self.on_move and time.monotonic() - self._cooldown.get(symbol, 0) > 120:
            self._cooldown[symbol] = time.monotonic()
            try:
                self.on_move(symbol)
            except Exception:
                log.exception("on_move failed")

    def _loop(self) -> None:
        from alpaca.data.live.stock import StockDataStream

        backoff = 2.0
        while not self._stop.is_set():
            try:
                stream = StockDataStream(self.api_key, self.secret, feed=self.feed)

                async def on_trade(t):
                    self._handle(t.symbol, float(t.price), getattr(t, "timestamp", None))

                stream.subscribe_trades(on_trade, *self.symbols)
                self.connected = True
                log.info("price stream connected (%d symbols)", len(self.symbols))
                stream.run()  # blocks until the connection drops
            except Exception as e:
                log.warning("price stream error: %s", e)
            self.connected = False
            if self._stop.wait(backoff):
                break
            backoff = min(backoff * 2, 60.0)
