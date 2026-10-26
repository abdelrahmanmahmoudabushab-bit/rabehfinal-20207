# Rahbeh — AI trading agents

A web app where a team of AI agents watches the US market, proposes day trades with written reasons, and,
if you allow it, places them in **your own** brokerage account under strict limits you set. In Research mode the app never buys on its own. Rahbeh never
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

Or with Docker (Postgres included): `cp api/.env.example api/.env && docker compose up --build`. Compose refuses to start unless `API_TOKEN` and `RAHBEH_PASSWORD` are set (in your shell or `.env`).

To go further, fill in `api/.env` (see `api/.env.example`):

| Key | Unlocks |
| --- | --- |
| `ANTHROPIC_API_KEY` | Claude agents (Analyst, Devil's advocate, Manager, Position keeper, Reviewer, Coach). Without it they run as transparent heuristics. |
| `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` | Real market data, news and an Alpaca **paper** account (`ALPACA_PAPER=true` by default). |
| `FINNHUB_API_KEY` | A second price source (the "two sources must agree" check only runs when it is set; without it one source is used) and earnings dates. **Live mode needs it:** without it the earnings date is unknown and live trades are blocked ("earnings date unknown"). Demo mode is unaffected. |
| `FMP_API_KEY` | Live fundamentals for company checks and halal ratios. |
| `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | Alerts on your phone. Both are required; with only one, no alerts are sent. |

## Data sources

The **Agents** page in the app shows each source's live status. Each source is optional; without its key the app falls back to a simulated or built-in value and says so. One exception: in live mode a missing `FINNHUB_API_KEY` means the earnings date is unknown, and the risk engine blocks the trade.

| Data | Source | Key |
| --- | --- | --- |
| Prices, minute bars, chart candles, news, market clock, orders | Alpaca (paper by default) | `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` |
| Company filings (8-K, 10-Q, 10-K, insider Form 4, 13D/G) | SEC EDGAR (free) | `SEC_USER_AGENT` (your contact email) |
| Second price source, earnings dates and EPS surprises, analyst ratings, economic calendar | Finnhub | `FINNHUB_API_KEY` |
| VIX, Fed funds rate, 10-year yield, oil | FRED, St. Louis Fed (free key) | `FRED_API_KEY` |
| Fundamentals, economic calendar fallback | Financial Modeling Prep | `FMP_API_KEY` |
| AI agents | Anthropic Claude | `ANTHROPIC_API_KEY` |

These are not wired yet: short interest, unusual options activity, earnings call transcripts, and Gulf/Egypt prices with Arabic news. Each needs a paid or regional data vendor.

## Backtesting: every trade is proven first

**Every trade the AI finds is backtested before it can reach you.** The Backtester (`api/rahbeh/backtest/`) works in these steps:

1. It works out which setup is firing: breakout, VWAP pullback, momentum, or opening-range breakout.
2. It tests that setup on the stock and 7 peers over 60 days of 5-minute history, **1,152 ways**: 9 filters (relative volume × RSI cap) × 128 exit rules (stop size × target × breakeven trail × max hold).
3. It picks the best variant using only the first 70% of history.
4. It judges that variant only on the last 30%, which it never saw.
5. It resamples the result **1,000 times** (Monte Carlo) to estimate the chance of a losing run.

A trade is blocked when there's no proven out-of-sample edge (`BACKTEST_GATE`). When there is one, the trade uses the tested stop, target and holding time instead of the Manager's guess (`BACKTEST_ADOPT_EXITS`).

**The Strategy lab page** runs all 4,608 variants across the whole watchlist, in about 5 seconds on 28 stocks × 60 days.

**Market regime.** Each session is labeled trending or choppy from the S&P 500's *previous* five sessions (never the day itself). The chosen variant's results are split by regime, and a trade is blocked when the variant lost money in the regime the market is in now (`min 10 trades`).

**Stricter bar for the winner.** Picking the best of ~1,000 variants flatters the pick, so the out-of-sample t-stat must clear `BACKTEST_MIN_OOS_T + BACKTEST_DEFLATE x ln(variants)` (about 1.2 to 1.5). The number of variants and the bar are shown on every backtest.

**Nightly precompute.** At 17:00 ET every stock x setup x filter pattern is tested and cached, so a trade found during the day gets its verdict instantly. The tested stop and target are always rebuilt from the live price. Backtests run in a separate worker process so they never block the scanner.

**Honesty rules**, all covered by tests (`tests/test_backtest.py`):
- Trades enter at the next bar's open, so there's no lookahead.
- Slippage is charged on entry and exit.
- If the stop and target fall in the same bar, the stop is assumed to hit first.
- Gaps through the stop fill at the worse open price.
- In live day-trading mode everything is flat by 15:50 ET (swing mode holds overnight, the demo market uses a 2-hour time stop, and tested trades use their tested max-hold).
- On pure random-walk data the tool finds **no** edge.
- On data with a planted edge it finds it.

**Demo caveat:** demo backtests run on simulated history, whose news bursts persist for several bars. That gives momentum setups an edge that real markets mostly don't have. Only backtests on real Alpaca history mean anything.

## Cost and execution controls

- **Cooldown:** a stock the agents rejected isn't re-analyzed (and re-billed) for 30 minutes unless new news lands.
- **Daily AI budget:** past it, agents use free rules until tomorrow. The Reviewer page shows cost per trade.
- **Rules vs Claude A/B:** every Claude analyst score is shadowed by the free rules, and both are checked 60 minutes later.
- **Position size** only ever shrinks from the 1% cap: tested edge below +0.30R, a volatile stock (ATR above 2% / 3%) and a setup that is losing live (half size after 8 live trades below zero, paused after 15 at -0.2R or worse) each scale it down. The reason is shown in the risk checks.
- **Models:** with `AGENT_TEAM=full` the News, Chart, Company and Mood readers use `SPECIALIST_MODEL` (Haiku by default, small and fast); the Analyst, Devil's advocate, Manager, Keeper, Reviewer and Coach use `CLAUDE_MODEL`. The deal finder analyses its shortlist in parallel.
- **Live prices:** in live mode a websocket feed updates prices as they print and a 1% move in a minute triggers a scan at once. Polling stays as the fallback. (Not yet verified against a live Alpaca account.)
- **Reviewer:** changes a rule only with 20+ trades and only if the change wins a replay over the last 14 calendar days (about 10 trading days).
- **Live vs backtest:** realized R per trade is compared with what the backtest promised.
- **Entries:** limit orders set `MAX_ENTRY_SLIP_BPS` (default 10 bp) above the live price at the moment of the order, so the app never chases a fast move. An idea expires when the live price is already more than `MAX_PLAN_DRIFT_PCT` (default 0.4%) above its planned entry. Risk is re-checked at the live price first. Unfilled orders are cancelled.
- **US pattern-day-trader rule:** enforced for accounts under $25k. Swing mode holds overnight instead.

## Deal finder (full loop on one page)

The **Deal finder** page runs the whole trade in four steps:

1. **Hunt:** the team checks the market mood. The Scanner ranks every stock, and the shortlist (at most `HUNT_DEPTH` stocks, default 5) runs the Data OK and cooldown checks, then gets the News reader, Chart reader, Company checker and Analyst. At most 3 finalists go to the Devil's advocate, then the Manager and the risk engine. If one fails, the next best is tried.
2. **Approve:** you see the deal on a chart with entry, stop and target, then choose the number of shares. You can't go above what the risk engine allows. Your own explicit "buy N shares" click here works in every mode, Research included (the risk engine and kill switch still apply); the automatic path never buys in Research mode, and Approve on the Ideas page is disabled there. The page shows the cost, the loss if the stop is hit, and the gain if the target is hit.
3. **Watch:** a bracket order is placed. The **Position keeper** agent re-checks the trade every cycle (with Claude, every `KEEPER_INTERVAL_SECONDS`). It can hold, raise the stop or sell, but it can only reduce risk.
4. **Sold:** the result is shown, and the Reviewer learns from it after the close.

Every hand-off appears live in the agent feed, with the skills each agent used (for rule-based agents, the skills they declare).

## The agent team

- **Specialists:** News reader, Chart reader, Company checker and Market mood each write a report.
- **Decision:** the Analyst combines the reports and scores the trade. The Devil's advocate argues against it, and the Manager answers the objection and sets the plan.
- **Safety:** the plain-code risk engine has the final say.
- **Own job, data, APIs and skills:** every agent from the plan is defined in `api/rahbeh/team/registry.py`, and each skill (tool) lists the data sources it reads (`team/skills.py`). With Claude, an agent can call only its own skills. Without a Claude key (and in the free starter team) the rule functions read the same data from the engine directly, and the trace shows the skills they declare. The News reader can't place orders, and the Position keeper can't buy.
- **Team size:** `AGENT_TEAM=starter` (the default) runs the specialists as free rules. `AGENT_TEAM=full` makes each specialist its own Claude agent: more calls, but on the small `SPECIALIST_MODEL`.
- **Market mood** sets position size: *calm* means full size, *careful* means half size, and *stormy* means no new trades.
- **Earnings:** no new position is opened when a company reports today or tomorrow. In live mode an unknown earnings date (no `FINNHUB_API_KEY`, or a failed fetch) also blocks the trade ("earnings date unknown"); demo mode is unaffected.

## How a trade happens (`api/rahbeh/engine.py`)

Every scan (60 s by default) a stock goes through the scan pipeline below: data check, scores, LAYA, halal, Analyst, Devil/Manager, backtest, risk engine, and the earnings and mood checks. Every "no" is logged and shown in **Decision log**. (The deal finder is a shorter path, see above.)

1. **Data OK?** — gaps, impossible jumps, zero volume, stale prices, and (only when `FINNHUB_API_KEY` is set) two sources disagreeing → the stock is paused 15 min and you're alerted (`pipeline/checks.py`).
2. **Feature scores in code** — trend, VWAP, RSI, ATR, volume ratio, momentum (`pipeline/features.py`).
3. **LAYA: worth a look?** — free, fast filter: headline sentiment (deduped, official news weighted up), activity, not over-stretched (`pipeline/laya.py`). Only the top few go on, which keeps Claude spend capped.
4. **Halal filter** (if on) — business screen + AAOIFI-style debt/cash ratios (`pipeline/halal.py`). The business screen uses tags from a built-in table for the 28 built-in stocks and a keyword match on the industry for any other symbol (banks, insurance, alcohol, tobacco, casino/gambling, weapons/defense/firearms, adult, pork). In live mode without `FMP_API_KEY` the debt and cash ratios come from built-in illustrative figures, not live filings.
5. **Analyst scores it** (Claude) — score must clear your line.
6. **Devil's advocate argues against it**, the **Manager** must answer the objection and sets entry, stop, target.
7. **Risk engine** — plain code with the final say (`pipeline/risk.py`): max 1% risk per trade (hard cap), daily loss stop, per-stock / per-sector exposure, open positions, trades per day, reward/risk, stop distance, entry window 09:35–15:30 ET, kill switch.

Then by mode: **Research** shows the idea; **Copilot** waits for your one tap (ideas expire after 15 min, and risk is re-checked at the live price before buying); **Autopilot** buys automatically. It unlocks after 5 completed Copilot trades in demo or 20 live; only trades opened by the app count (trades closed by a restart or outside the app don't), and demo (simulated) trades never count toward the live threshold.

Orders are **bracket orders** (stop + target held at the broker). Untested trades raise the stop to breakeven at +1R and trail it after +2R (tested trades use their tested rule: no trail or a breakeven trail). In live day-trading mode everything is closed by 15:50 ET; swing mode holds overnight, the demo market uses a 2-hour time stop, and tested trades use their tested max-hold. The kill switch closes every position the broker account holds (including ones Rahbeh didn't open) and cancels pending ideas; if a close fails you get a critical alert. The **Reviewer** runs at 16:30 ET, writes lessons the agents read the next day, and only changes the score line if the change beats the live rules on a replay of the day's trades.

## Layout

```
api/   Python + FastAPI, SQLAlchemy (SQLite default, Postgres in Docker), APScheduler
  rahbeh/market/    sim.py (demo market), live.py (Alpaca + Finnhub + FMP), extras.py (SEC, earnings, ratings, FRED)
  rahbeh/broker/    sim.py (paper sim), alpaca_broker.py (bracket + limit orders)
  rahbeh/pipeline/  checks, features, laya, halal, mood, risk, agents (Claude + rule fallbacks)
  rahbeh/team/      registry (every agent's job), skills (tools + data sources), hunter (deal finder)
  rahbeh/backtest/  vectorized engine, history loaders, Backtester service
  rahbeh/engine.py  the scan pipeline, execution, trade management, keeper, reviewer, briefing
  tests/            risk engine, data checks, halal, backtester, deal finder, bug regressions
web/   Next.js 16 + Tailwind 4 + shadcn/ui + lightweight-charts, black/white themes, English/Arabic (RTL)
```

The Reviewer page also shows each agent's cost and what its trades earned, and the health of every setup.

Run the tests: `cd api && .venv/bin/python -m pytest`. Lint: `ruff check api` and `cd web && npm run lint`.

## Security

- **App password:** set `RAHBEH_PASSWORD` for the web app and every visitor gets a login prompt. The username is `rahbeh`, or set `RAHBEH_USER`.
- **API token:** set `API_TOKEN` on both the web app and the API. The API then rejects any request without the token, and the web app adds it server-side so the browser never sees it.
- **Docker:** `docker compose` requires both settings and doesn't publish the API port at all.
- **Without them:** run it only on your own machine (`./dev.sh` listens on localhost).

## Honest limits of this version

- **Single user.** One app password (`RAHBEH_PASSWORD`) protects it; there are no separate user accounts or Stripe billing yet.
- **Long only.** There is no shorting, which also keeps the halal mode simple. Strategy choices are Day trader (flat by 15:50 ET in live mode) and Swing (holds overnight).
- **Backtests are not proof.** In demo mode they run on simulated history (see the caveat above). Even on real Alpaca history, past edge can vanish: run paper trading for weeks before any real money, and compare against the S&P 500 line on the dashboard.
- **The halal screen is a screening aid.** It is not a fatwa. Business tags are a built-in table for the 28 built-in stocks and a keyword match on the industry for others, so it can miss things; without `FMP_API_KEY` in live mode the ratios are illustrative figures, not live filings.
- **Live trading with real money** (`ALPACA_PAPER=false`) and offering Autopilot to other people both need legal and regulatory review in each country first.
- **Not financial advice.**
