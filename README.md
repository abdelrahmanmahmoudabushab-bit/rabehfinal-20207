# Rahbeh — AI trading agents

A web app where a team of AI agents watches the US market, proposes day trades with written reasons, and,
if you allow it, places them in **your own** brokerage account under strict limits you set. Rahbeh never
holds client money.

The home screen is a TradingView-style terminal: watchlist, real candlestick charts (TradingView's open-source
`lightweight-charts`) with volume, EMA 9/21, session VWAP and an RSI pane, your entries/exits/stop/target drawn on the
chart, key stats, news, and an account panel. An **AI** button (or ⌘K) on every screen opens an assistant that knows
which stock you're looking at; **Analyze with AI** runs the whole agent team on any chart and can send the result to
Trade ideas. Black and white themes.

It runs fully **out of the box with no keys** on a built-in market simulator, so you can click through every
feature before connecting anything real.

## Quick start

```bash
./dev.sh            # API on :8000, web app on http://localhost:3000
```

Or with Docker (Postgres included): `cp api/.env.example api/.env && docker compose up --build`.

To go further, fill in `api/.env` (see `api/.env.example`):

| Key | Unlocks |
| --- | --- |
| `ANTHROPIC_API_KEY` | Claude agents (Analyst, Devil's advocate, Manager, Reviewer, Coach). Without it they run as transparent heuristics. |
| `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` | Real market data, news and an Alpaca **paper** account (`ALPACA_PAPER=true` by default). |
| `FINNHUB_API_KEY` | A second price source, so "two sources must agree" is enforced. |
| `FMP_API_KEY` | Live fundamentals for company checks and halal ratios. |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Alerts on your phone. |

## How a trade happens (`api/rahbeh/engine.py`)

Every scan (60 s by default) each stock must pass seven checks. Every "no" is logged and shown in **Decision log**.

1. **Data OK?** — gaps, impossible jumps, zero volume, stale prices, two sources disagreeing → the stock is paused 15 min and you're alerted (`pipeline/checks.py`).
2. **Feature scores in code** — trend, VWAP, RSI, ATR, volume ratio, momentum (`pipeline/features.py`).
3. **LAYA: worth a look?** — free, fast filter: headline sentiment (deduped, official news weighted up), activity, not over-stretched (`pipeline/laya.py`). Only the top few go on, which keeps Claude spend capped.
4. **Halal filter** (if on) — business screen + AAOIFI-style debt/cash ratios (`pipeline/halal.py`).
5. **Analyst scores it** (Claude) — score must clear your line.
6. **Devil's advocate argues against it**, the **Manager** must answer the objection and sets entry, stop, target.
7. **Risk engine** — plain code with the final say (`pipeline/risk.py`): max 1% risk per trade (hard cap), daily loss stop, per-stock / per-sector exposure, open positions, trades per day, reward/risk, stop distance, entry window 09:35–15:30 ET, kill switch.

Then by mode: **Research** shows the idea; **Copilot** waits for your one tap (ideas expire after 15 min, and risk is re-checked at the live price before buying); **Autopilot** (unlocks after 5 completed Copilot trades in demo, 20 live) buys automatically.

Orders are **bracket orders** (stop + target held at the broker). Stops rise to breakeven at +1R and trail after +2R; everything is closed by 15:50 ET. The **Reviewer** runs at 16:30 ET, writes lessons the agents read the next day, and only changes the score line if the change beats the live rules on a replay of the day's trades.

## Layout

```
api/   Python + FastAPI, SQLAlchemy (SQLite default, Postgres in Docker), APScheduler
  rahbeh/market/    sim.py (demo market), live.py (Alpaca + Finnhub + FMP)
  rahbeh/broker/    sim.py (paper sim), alpaca_broker.py (bracket orders)
  rahbeh/pipeline/  checks, features, laya, halal, risk, agents (Claude + fallbacks)
  rahbeh/engine.py  the seven checks, execution, trade management, reviewer, briefing
  tests/            risk engine, data checks, LAYA, halal, full demo loop
web/   Next.js 16 + Tailwind 4 + shadcn/ui + lightweight-charts, black/white themes, English/Arabic (RTL)
```

Run the tests: `cd api && .venv/bin/python -m pytest`.

## Honest limits of this version

- **Single user.** There are no accounts or login, and no Stripe yet. Run it locally or behind your own auth before exposing it.
- **Long only, intraday only.** There is no shorting, which also keeps the halal mode simple.
- **Not backtested.** The demo simulator shows how the app works, not whether the strategy makes money. Run paper trading for weeks before any real money, and compare against the S&P 500 line on the dashboard.
- **The halal screen is a screening aid.** It is not a fatwa.
- **Live trading with real money** (`ALPACA_PAPER=false`) and offering Autopilot to other people both need legal and regulatory review in each country first.
- **Not financial advice.**
