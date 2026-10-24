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

## Data sources

The **Agents** page in the app shows each source's live status. Each source is optional; without its key the app falls back to a simulated or built-in value and says so.

| Data | Source | Key |
| --- | --- | --- |
| Prices, minute bars, chart candles, news, market clock, orders | Alpaca (paper by default) | `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` |
| Company filings (8-K, 10-Q, 10-K, insider Form 4, 13D/G) | SEC EDGAR (free) | `SEC_USER_AGENT` (your contact email) |
| Second price source, earnings dates and EPS surprises, analyst ratings, economic calendar | Finnhub | `FINNHUB_API_KEY` |
| VIX, Fed funds rate, 10-year yield, oil | FRED, St. Louis Fed (free key) | `FRED_API_KEY` |
| Fundamentals, economic calendar fallback | Financial Modeling Prep | `FMP_API_KEY` |
| AI agents | Anthropic Claude | `ANTHROPIC_API_KEY` |

These are not wired yet: short interest, unusual options activity, earnings call transcripts, and Gulf/Egypt prices with Arabic news. Each needs a paid or regional data vendor.

## Deal finder (full loop on one page)

The **Deal finder** page runs the whole trade in four steps:

1. **Hunt:** the team checks the market mood. The Scanner ranks every stock, and the top few (`HUNT_DEPTH`, default 5) get the News reader, Chart reader, Company checker and Analyst. The best goes to the Devil's advocate, the Manager and the risk engine. If it fails, the next best is tried.
2. **Approve:** you see the deal on a chart with entry, stop and target, then choose the number of shares. You can't go above what the risk engine allows. The page shows the cost, the loss if the stop is hit, and the gain if the target is hit.
3. **Watch:** a bracket order is placed. The **Position keeper** agent re-checks the trade every cycle (with Claude, every `KEEPER_INTERVAL_SECONDS`). It can hold, raise the stop or sell, but it can only reduce risk.
4. **Sold:** the result is shown, and the Reviewer learns from it after the close.

Every hand-off appears live in the agent feed, with the skills each agent used.

## The agent team

- **Specialists:** News reader, Chart reader, Company checker and Market mood each write a report.
- **Decision:** the Analyst combines the reports and scores the trade. The Devil's advocate argues against it, and the Manager answers the objection and sets the plan.
- **Safety:** the plain-code risk engine has the final say.
- **Own job, data, APIs and skills:** every agent from the plan is defined in `api/rahbeh/team/registry.py`, and each skill (tool) is backed by one data source (`team/skills.py`). With Claude, an agent can call only its own skills. The News reader can't place orders, and the Position keeper can't buy.
- **Team size:** `AGENT_TEAM=starter` (the default) runs the specialists as free rules. `AGENT_TEAM=full` makes each specialist its own Claude agent, at roughly twice the agent cost.
- **Market mood** sets position size: *calm* means full size, *careful* means half size, and *stormy* means no new trades.
- **Earnings:** no new position is opened when a company reports today or tomorrow.

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
