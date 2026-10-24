"""The trading engine: runs the seven checks, executes approved trades, manages open trades,
and runs the nightly review. One instance per process."""

import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, select

from .broker.base import Broker
from .config import Settings
from .backtest.service import Backtester
from .db import (
    Shadow,
    Alert, Briefing, DecisionLog, EquitySnapshot, Proposal, Review, SessionLocal, StoredBar, Trade, UserSettings,
)
from .market.base import MarketData
from .market.extras import Extras, LiveExtras, SimExtras
from .market.universe import BENCHMARK, sector_of
from .pipeline import checks, features, halal, laya, mood, risk
from .pipeline.agents import Agents, suggested_levels

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
PROPOSAL_TTL = timedelta(minutes=15)
ANALYSIS_CACHE_SECONDS = 120
REVIEW_MIN_TRADES = 20
PAUSE_AFTER_BAD_DATA = timedelta(minutes=15)
DEMO_TIME_STOP = timedelta(minutes=120)  # the always-open demo has no 15:50 close, so trades time out instead


class Engine:
    def __init__(self, s: Settings, market: MarketData, broker: Broker, agents: Agents, extras: Extras | None = None):
        self.s, self.market, self.broker, self.agents = s, market, broker, agents
        self.extras: Extras = extras or (SimExtras(market) if s.demo else LiveExtras(s))
        self.agents.bind(self)
        self.backtester = Backtester(s, market.universe())
        self.hunts: dict = {}  # deal finder runs (team/hunter.py), kept in memory
        self.latest_hunt_id: str | None = None
        self._hunt_lock = threading.Lock()
        self.mood: mood.Mood | None = None
        self.mood_report: dict = {}
        self._mood_report_at = 0.0
        self.lock = threading.RLock()
        self.paused: dict[str, datetime] = {}
        self._alerted: dict[str, datetime] = {}
        self.last_cycle: datetime | None = None
        self.last_scan_summary: dict = {}
        self.session_rules = not (s.demo and s.demo_always_open)
        self.cycle_lock = threading.Lock()
        self._analysis_cache: dict[str, tuple[float, tuple]] = {}
        self.cooldowns: dict[str, tuple[datetime, int]] = {}  # symbol -> (until, headline count when rejected)

    # ---- helpers ---------------------------------------------------------------------------
    def settings_row(self, db) -> UserSettings:
        return db.get(UserSettings, 1)

    def limits(self, u: UserSettings) -> risk.Limits:
        return risk.Limits(u.risk_per_trade_pct, u.daily_loss_limit_pct, u.max_position_pct, u.max_sector_pct,
                           u.max_open_positions, u.max_trades_per_day, u.min_reward_risk, list(u.allowed_symbols or []))

    def today_et(self) -> str:
        return self.market.now().astimezone(ET).date().isoformat()

    def _day_start_utc(self) -> datetime:
        d = self.market.now().astimezone(ET).replace(hour=0, minute=0, second=0, microsecond=0)
        return d.astimezone(UTC)

    def log(self, db, stage: str, outcome: str, reason: str, symbol: str | None = None, detail: dict | None = None):
        db.add(DecisionLog(at=self.market.now(), symbol=symbol, stage=stage, outcome=outcome, reason=reason, detail=detail or {}))

    def alert(self, db, level: str, title: str, body: str = "", dedupe_key: str | None = None):
        if dedupe_key:
            last = self._alerted.get(dedupe_key)
            if last and datetime.now(UTC) - last < timedelta(hours=1):
                return
            self._alerted[dedupe_key] = datetime.now(UTC)
        db.add(Alert(level=level, title=title, body=body))
        if self.s.telegram_bot_token and self.s.telegram_chat_id:
            try:
                httpx.post(f"https://api.telegram.org/bot{self.s.telegram_bot_token}/sendMessage",
                           json={"chat_id": self.s.telegram_chat_id, "text": f"{title}\n{body}".strip()}, timeout=5)
            except Exception as e:
                log.warning("telegram failed: %s", e)

    def daytrades_5d(self, db) -> int:
        """Round trips opened and closed on the same day over the last 5 business days."""
        since = self.market.now() - timedelta(days=7)
        rows = db.scalars(select(Trade).where(Trade.opened_at >= since, Trade.closed_at.is_not(None))).all()
        n = 0
        for t in rows:
            o = (t.opened_at if t.opened_at.tzinfo else t.opened_at.replace(tzinfo=UTC)).astimezone(ET).date()
            c = (t.closed_at if t.closed_at.tzinfo else t.closed_at.replace(tzinfo=UTC)).astimezone(ET).date()
            n += o == c and t.exit_reason != "demo restart"
        return n

    def risk_context(self, db, u: UserSettings) -> risk.RiskContext:
        positions = self.broker.positions()
        n_today = db.scalar(select(func.count(Trade.id)).where(Trade.opened_at >= self._day_start_utc())) or 0
        acct = self.broker.account()
        return risk.RiskContext(
            account=acct, positions=positions,
            sector_of={p.symbol: sector_of(p.symbol) for p in positions},
            realized_pnl_today=0.0, trades_today=n_today, kill_switch=u.kill_switch,
            now=self.market.now(), session_rules=self.session_rules,
            mood_level=self.mood.level if self.mood else "calm",
            mood_multiplier=self.mood.risk_multiplier if self.mood else 1.0,
            daytrades_5d=max(acct.daytrade_count, self.daytrades_5d(db)),
            swing=u.strategy == "swing",
        )

    def earnings_ctx(self, symbol: str) -> dict:
        e = self.extras.earnings(symbol)
        return {"next_date": e.next_date, "next_hour": e.next_hour, "eps_estimate": e.eps_estimate,
                "days_until": e.days_until(self.market.now().astimezone(ET).date()), "history": e.history}

    def ratings_ctx(self, symbol: str) -> dict | None:
        r = self.extras.ratings(symbol)
        if not r:
            return None
        return {"period": r.period, "strong_buy": r.strong_buy, "buy": r.buy, "hold": r.hold, "sell": r.sell,
                "strong_sell": r.strong_sell, "total": r.total, "score": round(r.score, 2) if r.score else None}

    def update_mood(self) -> None:
        """Market mood: recomputed every cycle from VIX, rates, the S&P 500, breadth and the economic calendar."""
        try:
            spy = self.market.minute_bars(BENCHMARK, 400)
            spy_chg = features.compute(spy, self.market.daily_bars(BENCHMARK, 5)).change_day_pct if len(spy) > 1 else 0.0
            ups = total = 0
            for sym in self.market.universe():
                bars = self.market.minute_bars(sym, 400)
                if len(bars) > 1:
                    total += 1
                    ups += features.compute(bars, self.market.daily_bars(sym, 5)).change_day_pct > 0
            new = mood.assess(self.extras.mood_inputs(), spy_chg, ups / total * 100 if total else 50, self.market.now())
        except Exception as e:
            log.warning("mood update failed: %s", e)
            return
        old = self.mood.level if self.mood else None
        self.mood = new
        if old is not None and old != new.level:
            with SessionLocal() as db:
                self.log(db, "mood", "alert" if new.level != "calm" else "info", f"market mood {old} → {new.level}: {'; '.join(new.reasons)}")
                self.alert(db, "warn" if new.level != "calm" else "info", f"Market mood: {new.level}", new.summary)
                db.commit()
        if time.monotonic() - self._mood_report_at > 900 or old != new.level:
            self.mood_report = self.agents.mood_report(new.to_dict())
            self._mood_report_at = time.monotonic()

    def stock_context(self, symbol: str, with_news: bool = True) -> dict | None:
        """Everything the agents may see about one stock, already checked and time-stamped."""
        bars = self.market.minute_bars(symbol, 240)
        daily = self.market.daily_bars(symbol, 60)
        if len(bars) < 2:
            return None
        f = features.compute(bars, daily)
        fd = self.market.fundamentals(symbol)
        news = self.market.news([symbol], 30) if with_news else []
        lr = laya.evaluate(symbol, f, news, self.market.now())
        company = None
        if fd:
            company = {
                "name": fd.name, "sector": fd.sector, "industry": fd.industry,
                "market_cap_b": round(fd.market_cap / 1e9, 1), "revenue_b": round(fd.revenue / 1e9, 1),
                "net_margin": round(fd.net_income / fd.revenue, 3) if fd.revenue else None,
                "debt_to_mcap": round(fd.total_debt / fd.market_cap, 3) if fd.market_cap else None,
                "next_earnings": fd.next_earnings,
                "next_earnings_soon": bool(fd.next_earnings and fd.next_earnings <= (self.market.now() + timedelta(days=1)).date().isoformat()),
            }
        return {
            "symbol": symbol, "as_of": self.market.now().isoformat(), "features": f.to_dict(),
            "laya": {"sentiment": lr.sentiment, "score": lr.score, "reasons": lr.reasons, "headlines": lr.headlines,
                     "worth_a_look": lr.worth_a_look, "company_news": lr.company_news},
            "company": company, "suggested_levels": suggested_levels(f.to_dict()),
            "earnings": self.earnings_ctx(symbol), "ratings": self.ratings_ctx(symbol),
            "filings": [vars(x) for x in self.extras.filings(symbol, 6)],
            "market_mood": {"level": self.mood.level, "reasons": self.mood.reasons, "summary": self.mood.summary,
                            "vix": self.mood.vix, "spy_change_pct": self.mood.spy_change_pct} if self.mood else None,
        }

    # ---- the cycle ---------------------------------------------------------------------------
    def cycle(self) -> dict:
        if not self.cycle_lock.acquire(blocking=False):
            return {"skipped": "a scan is already running"}
        try:
            return self._cycle()
        finally:
            self.cycle_lock.release()

    def _cycle(self) -> dict:
        refresh = getattr(self.market, "refresh", None) or getattr(self.market, "tick", None)
        if refresh:
            refresh()
        self.update_mood()
        self.manage_positions()
        self.run_keepers()
        self.fill_shadows()
        summary = self.scan() if self.market.is_open() else {"skipped": "market closed"}
        self.snapshot()
        self.last_cycle = datetime.now(UTC)
        self.last_scan_summary = summary
        return summary

    def snapshot(self) -> None:
        try:
            acct = self.broker.account()
            spy = self.market.quote(BENCHMARK)
            with SessionLocal() as db:
                db.add(EquitySnapshot(at=self.market.now(), equity=acct.equity, benchmark=spy.price if spy else 0))
                db.commit()
        except Exception as e:
            log.warning("snapshot failed: %s", e)

    def scan(self) -> dict:
        now = self.market.now()
        summary = {"at": now.isoformat(), "checked": 0, "data_bad": 0, "laya_yes": 0, "halal_no": 0, "agent_runs": 0, "proposals": 0}
        with SessionLocal() as db:
            u = self.settings_row(db)
            if u.kill_switch:
                return {**summary, "skipped": "kill switch on"}
            if self.mood and self.mood.level == "stormy":
                self.log(db, "mood", "no", f"market mood stormy — no new trades ({'; '.join(self.mood.reasons)})")
                db.commit()
                return {**summary, "skipped": "market mood stormy"}
            ctx_risk = self.risk_context(db, u)
            if risk.daily_loss_hit(ctx_risk, self.limits(u)):
                self.alert(db, "critical", "Daily loss limit hit — trading paused for today",
                           f"Today's P&L {risk.day_pnl(ctx_risk):+,.2f}", dedupe_key=f"dailyloss:{self.today_et()}")
                db.commit()
                return {**summary, "skipped": "daily loss limit hit"}

            held = {p.symbol for p in ctx_risk.positions}
            live_props = set(db.scalars(select(Proposal.symbol).where(Proposal.status == "pending")).all())
            self._expire_proposals(db)
            news = self.market.news(None, 100)
            candidates, laya_no = [], {}

            for sym in self.market.universe():
                if sym in held or sym in live_props:
                    continue
                if (until := self.paused.get(sym)) and until > now:
                    continue
                summary["checked"] += 1
                bars = self.market.minute_bars(sym, 240)
                # 1. Data OK?
                dc = checks.check_data(bars, self.market.quote(sym), self.market.second_quote(sym), now)
                if not dc.ok:
                    summary["data_bad"] += 1
                    self.paused[sym] = now + PAUSE_AFTER_BAD_DATA
                    self.log(db, "data_check", "no", "; ".join(dc.problems), sym, {"paused_until": self.paused[sym].isoformat()})
                    self.alert(db, "warn", f"{sym} paused: bad data", "; ".join(dc.problems), dedupe_key=f"data:{sym}")
                    continue
                self._store_bars(db, sym, bars[-5:])
                # 2. Feature scores in code, 3. LAYA: worth a look?
                f = features.compute(bars, self.market.daily_bars(sym, 60))
                lr = laya.evaluate(sym, f, news, now)
                if not lr.worth_a_look:
                    laya_no[sym] = lr.reasons or ["quiet"]
                    continue
                summary["laya_yes"] += 1
                # 4. Halal filter (if on)
                if u.halal_only:
                    hr = halal.screen(self.market.fundamentals(sym))
                    if not hr.passes:
                        summary["halal_no"] += 1
                        self.log(db, "halal", "no", "; ".join(hr.reasons), sym)
                        continue
                if self._cooling(sym):
                    summary["cooling"] = summary.get("cooling", 0) + 1
                    continue
                candidates.append((lr.score, sym))

            if laya_no:
                self.log(db, "laya", "no", f"{len(laya_no)} stocks not worth a look", None, laya_no)
            db.commit()

            # Only the top few reach the paid agents
            candidates.sort(reverse=True)
            lessons = self._latest_lessons(db)
            for _, sym in candidates[: self.s.max_candidates_per_cycle]:
                summary["agent_runs"] += 1
                if self._run_agents(db, u, sym, lessons):
                    summary["proposals"] += 1
                db.commit()
        return summary

    def _run_agents(self, db, u: UserSettings, sym: str, lessons: list[str]) -> bool:
        ctx = self.stock_context(sym)
        if not ctx:
            return False
        ctx["lessons_from_reviewer"] = lessons
        ctx["user_strategy"] = u.strategy
        # 5. Specialists report (news, chart, company, mood), then the Analyst combines and scores
        team = self.agents.team(ctx)
        team["mood"] = {**self.mood_report, "level": self.mood.level if self.mood else "calm"}
        ctx["team_reports"] = team
        rep, src = self.agents.analyst(ctx)
        self.record_shadow(sym, ctx, rep, src, u.score_threshold)
        if rep.direction != "long" or rep.score < u.score_threshold:
            self._cooldown(sym)
            self.log(db, "score", "no", f"score {rep.score} below line {u.score_threshold}" if rep.direction == "long"
                     else f"analyst says skip (score {rep.score}): {rep.thesis}", sym, {"analyst": rep.model_dump(), "team": team})
            return False
        # 6. Devil's advocate, objection answered?
        dv, _ = self.agents.devil(ctx, rep)
        mg, _ = self.agents.manager(ctx, rep, dv)
        if not mg.objection_answered or mg.decision != "trade":
            self._cooldown(sym)
            self.log(db, "devils_advocate", "no", f"objection not answered: {dv.objection}", sym,
                     {"devil": dv.model_dump(), "manager": mg.model_dump()})
            return False
        # 7. Backtester: has this setup made money on history, out of sample?
        btr = self.backtest_trade(sym)
        if not self.backtest_ok(btr):
            self._cooldown(sym)
            self.log(db, "backtest", "no", f"no proven edge — {self.backtest_brief(btr)}. " + "; ".join(btr.get("reasons", [])), sym,
                     {"verdict": btr.get("verdict"), "setup": btr.get("setup"), "variants": btr.get("variants_tested")})
            return False
        entry, stop, target, tuned = self.tuned_levels(mg, btr)
        # 8. Risk engine: within limits?
        req = risk.TradeRequest(sym, sector_of(sym), entry, stop, target, ctx["earnings"]["days_until"])
        rd = risk.evaluate(req, self.risk_context(db, u), self.limits(u))
        prop = Proposal(
            symbol=sym, score=rep.score, entry=entry, stop=stop, target=target, qty=rd.qty,
            risk_amount=rd.risk_amount, thesis=rep.thesis, analyst=rep.model_dump(), devil=dv.model_dump(),
            manager={**mg.model_dump(), "tuned_by_backtest": tuned}, features={**ctx["features"], "headlines": ctx["laya"]["headlines"]},
            risk_checks=rd.as_list(), status="blocked", agent_source=src, created_at=self.market.now(), team=team, backtest=btr,
        )
        db.add(prop)
        if not rd.approved:
            prop.status_reason = rd.reason
            self._cooldown(sym)
            self.log(db, "risk", "no", rd.reason, sym, {"checks": rd.as_list()})
            return False
        db.flush()
        # Which mode?
        if u.mode == "research":
            prop.status = "idea"
            self.alert(db, "info", f"Idea: {sym} (score {rep.score})", rep.thesis)
        elif u.mode == "copilot":
            prop.status = "pending"
            self.alert(db, "info", f"Trade ready for approval: {sym}", f"Buy {rd.qty} @ ~{mg.entry:.2f}, stop {mg.stop:.2f}, target {mg.target:.2f}")
        else:
            self.execute(db, prop, u)
        return True

    def analyze(self, symbol: str, propose: bool = False) -> dict:
        """Run the full agent team on one stock on request ("Analyze with AI"), skipping only the LAYA pre-filter.

        Nothing is bought here. With propose=True a passing result becomes a trade idea that still needs approval.
        """
        sym = symbol.upper()
        ctx = self.stock_context(sym)
        if not ctx:
            raise ValueError(f"no data for {sym}")
        now = self.market.now()
        dc = checks.check_data(self.market.minute_bars(sym, 240), self.market.quote(sym), self.market.second_quote(sym), now)
        hr = halal.screen(self.market.fundamentals(sym))
        with SessionLocal() as db:
            u = self.settings_row(db)
            cached = self._analysis_cache.get(sym)
            if propose and cached and time.monotonic() - cached[0] < ANALYSIS_CACHE_SECONDS:
                rep, dv, mg, src, team = cached[1]  # "Send to Ideas" right after an analysis: reuse it, don't pay twice
            else:
                ctx["lessons_from_reviewer"] = self._latest_lessons(db)
                ctx["user_strategy"] = u.strategy
                team = self.agents.team(ctx)
                team["mood"] = {**self.mood_report, "level": self.mood.level if self.mood else "calm"}
                ctx["team_reports"] = team
                rep, src = self.agents.analyst(ctx)
                dv, _ = self.agents.devil(ctx, rep)
                mg, _ = self.agents.manager(ctx, rep, dv)
                self._analysis_cache[sym] = (time.monotonic(), (rep, dv, mg, src, team))
            days = ctx["earnings"]["days_until"]
            btr = self.backtest_trade(sym)
            entry, stop, target, tuned = self.tuned_levels(mg, btr)
            rd = risk.evaluate(risk.TradeRequest(sym, sector_of(sym), entry, stop, target, days), self.risk_context(db, u), self.limits(u))
            gates = [
                {"name": "Data OK", "passed": dc.ok, "detail": "; ".join(dc.problems) or "clean"},
                {"name": "Halal", "passed": hr.passes or not u.halal_only,
                 "detail": ("passes" if hr.passes else "; ".join(hr.reasons)) + ("" if u.halal_only else " (filter off)")},
                {"name": "Score line", "passed": rep.direction == "long" and rep.score >= u.score_threshold,
                 "detail": f"{rep.score} vs line {u.score_threshold}" + ("" if rep.direction == "long" else " — analyst says skip")},
                {"name": "Objection answered", "passed": mg.objection_answered and mg.decision == "trade", "detail": dv.objection},
                {"name": "Market mood", "passed": not self.mood or self.mood.level != "stormy",
                 "detail": f"{self.mood.level}: {'; '.join(self.mood.reasons)}" if self.mood else "not assessed yet"},
                {"name": "Earnings", "passed": days is None or not 0 <= days <= risk.EARNINGS_BLACKOUT_DAYS,
                 "detail": f"next report in {days} day(s)" if days is not None else "date unknown"},
                {"name": "Backtest", "passed": self.backtest_ok(btr), "detail": f"{btr.get('verdict')}: {self.backtest_brief(btr)}"},
                {"name": "Risk engine", "passed": rd.approved, "detail": rd.reason},
            ]
            verdict = all(g["passed"] for g in gates)
            proposal_id = None
            if propose and verdict:
                prop = Proposal(
                    symbol=sym, score=rep.score, entry=entry, stop=stop, target=target, qty=rd.qty,
                    risk_amount=rd.risk_amount, thesis=rep.thesis, analyst=rep.model_dump(), devil=dv.model_dump(),
                    manager={**mg.model_dump(), "tuned_by_backtest": tuned}, features={**ctx["features"], "headlines": ctx["laya"]["headlines"]},
                    risk_checks=rd.as_list(), status="idea" if u.mode == "research" else "pending",
                    status_reason="requested from chart", agent_source=src, created_at=now, team=team, backtest=btr,
                )
                db.add(prop)
                db.flush()
                proposal_id = prop.id
                self.log(db, "user", "info", f"analysis requested from chart → idea #{prop.id}", sym)
            db.commit()
        return {
            "symbol": sym, "source": src, "verdict": "trade" if verdict else "no trade", "gates": gates,
            "analyst": rep.model_dump(), "devil": dv.model_dump(), "manager": mg.model_dump(),
            "plan": {"entry": entry, "stop": stop, "target": target, "qty": rd.qty, "risk_amount": rd.risk_amount, "tuned_by_backtest": tuned},
            "backtest": btr,
            "risk_checks": rd.as_list(), "proposal_id": proposal_id, "team": team,
        }

    def _expire_proposals(self, db) -> None:
        cutoff = self.market.now() - PROPOSAL_TTL
        for p in db.scalars(select(Proposal).where(Proposal.status.in_(["pending", "idea"]))).all():
            created = p.created_at if p.created_at.tzinfo else p.created_at.replace(tzinfo=UTC)
            if created < cutoff:
                p.status, p.status_reason = "expired", "price may have moved; proposals last 15 minutes"

    def _headline_count(self, symbol: str) -> int:
        return sum(1 for n in self.market.news([symbol], 50) if symbol in n.symbols)

    def _cooldown(self, symbol: str) -> None:
        """After the agents say no, don't pay to ask them again for a while — unless new news arrives."""
        self.cooldowns[symbol] = (self.market.now() + timedelta(minutes=self.s.agent_cooldown_minutes), self._headline_count(symbol))

    def _cooling(self, symbol: str) -> bool:
        hit = self.cooldowns.get(symbol)
        if not hit:
            return False
        until, seen = hit
        if self.market.now() >= until or self._headline_count(symbol) > seen:
            self.cooldowns.pop(symbol, None)
            return False
        return True

    def backtest_trade(self, symbol: str) -> dict:
        """Backtester agent: test this setup 1,000+ ways on history before the trade can go further."""
        try:
            return self.backtester.for_trade(symbol, self.market.minute_bars(symbol, 400))
        except Exception as e:
            log.exception("backtest failed for %s", symbol)
            return {"verdict": "error", "reasons": [f"backtest failed: {e}"], "variants_tested": 0}

    def backtest_ok(self, btr: dict) -> bool:
        return not self.s.backtest_gate or btr.get("verdict") == "edge"

    def tuned_levels(self, mg, btr: dict) -> tuple[float, float, float, bool]:
        """Entry, stop, target: the tested variant's exits when they proved an edge, otherwise the Manager's."""
        tp = btr.get("tuned_plan")
        if self.s.backtest_adopt_exits and btr.get("verdict") == "edge" and tp and tp["stop"] < tp["entry"] < tp["target"]:
            return tp["entry"], tp["stop"], tp["target"], True
        return mg.entry, mg.stop, mg.target, False

    @staticmethod
    def backtest_brief(btr: dict) -> str:
        best = btr.get("best") or {}
        o = best.get("oos") or {}
        if not best:
            return "; ".join(btr.get("reasons", [])) or btr.get("verdict", "")
        return (f"{btr.get('variants_tested', 0):,} variants of {btr.get('setup')} on {len(btr.get('basket', []))} stocks; "
                f"best out of sample {o.get('exp_r', 0):+.2f}R over {int(o.get('n', 0))} trades, win {o.get('win', 0):.0%}")

    # ---- rules vs Claude A/B ------------------------------------------------------------------
    def record_shadow(self, symbol: str, ctx: dict, rep, src: str, threshold: int) -> None:
        """When Claude scores a stock, also score it with the free rules and remember both. Forward returns are
        filled in later, so we can measure whether Claude's extra cost buys better picks."""
        if src != "claude":
            return
        from .pipeline.agents import _heuristic_analyst

        rules = _heuristic_analyst(ctx)
        with SessionLocal() as db:
            db.add(Shadow(at=self.market.now(), symbol=symbol, price=ctx["features"]["price"], threshold=threshold,
                          claude_score=rep.score, claude_go=rep.direction == "long" and rep.score >= threshold,
                          rules_score=rules.score, rules_go=rules.direction == "long" and rules.score >= threshold))
            db.commit()

    def fill_shadows(self) -> None:
        now = self.market.now()
        with SessionLocal() as db:
            rows = db.scalars(select(Shadow).where(Shadow.fwd_60.is_(None)).limit(200)).all()
            for r in rows:
                at = r.at if r.at.tzinfo else r.at.replace(tzinfo=UTC)
                q = self.market.quote(r.symbol)
                if not q:
                    continue
                if r.fwd_30 is None and now - at >= timedelta(minutes=30):
                    r.fwd_30 = round((q.price / r.price - 1) * 100, 4)
                if now - at >= timedelta(minutes=60):
                    r.fwd_60 = round((q.price / r.price - 1) * 100, 4)
            db.commit()

    def _latest_lessons_safe(self) -> list[str]:
        with SessionLocal() as db:
            return self._latest_lessons(db)

    def _latest_lessons(self, db) -> list[str]:
        r = db.scalar(select(Review).order_by(Review.id.desc()))
        return list(r.lessons) if r else []

    def _store_bars(self, db, sym: str, bars) -> None:
        for b in bars:
            db.merge(StoredBar(symbol=sym, ts=b.ts, o=b.o, h=b.h, l=b.l, c=b.c, v=b.v, source=self.market.name))

    # ---- execution -------------------------------------------------------------------------
    def execute(self, db, prop: Proposal, u: UserSettings, qty: int | None = None, origin: str = "scanner") -> tuple[bool, str]:
        """Re-check risk at the current price, then send the bracket order. qty: the user's chosen size,
        which may be smaller than, but never larger than, what the risk engine allows."""
        with self.lock:
            q = self.market.quote(prop.symbol)
            if not q:
                return False, "no live price"
            drift = q.price / prop.entry - 1
            if drift > 0.004:
                prop.status, prop.status_reason = "expired", f"price ran {drift:.2%} past the planned entry"
                return False, prop.status_reason
            # keep the stop/target distances, re-anchored to the live price
            entry, stop, target = q.price, prop.stop, prop.target
            days = self.earnings_ctx(prop.symbol)["days_until"]
            rd = risk.evaluate(risk.TradeRequest(prop.symbol, sector_of(prop.symbol), entry, stop, target, days),
                               self.risk_context(db, u), self.limits(u))
            prop.risk_checks = rd.as_list()
            if not rd.approved:
                prop.status, prop.status_reason = "blocked", rd.reason
                self.log(db, "risk", "no", rd.reason, prop.symbol, {"at_execution": True})
                return False, rd.reason
            if qty is not None and qty > rd.qty:
                return False, f"the risk engine allows at most {rd.qty} shares right now"
            size = qty if qty is not None else rd.qty
            if size < 1:
                return False, "quantity must be at least 1"
            limit = round(entry * (1 + self.s.max_entry_slip_bps / 10_000), 2)  # never chase more than this
            res = self.broker.submit_bracket(prop.symbol, size, stop, target, entry, limit_price=limit)
            if not res.ok:
                prop.status, prop.status_reason = "blocked", res.message
                self.log(db, "broker", "no", res.message, prop.symbol)
                self.alert(db, "warn", f"Order failed: {prop.symbol}", res.message)
                return False, res.message
            fill = res.fill_price or entry
            prop.status, prop.qty = "executed", size
            db.add(Trade(
                proposal_id=prop.id, symbol=prop.symbol, sector=sector_of(prop.symbol), qty=size, entry_price=fill,
                initial_stop=stop, stop=stop, target=target, broker_order_id=res.order_id, mode=u.mode,
                opened_at=self.market.now(), notes=[], origin=origin, peak_price=fill, keeper_log=[],
                plan=_trade_plan(prop),
            ))
            self.log(db, "execution", "yes", f"bought {size} @ {fill:.2f}", prop.symbol)
            self.alert(db, "info", f"Bought {size} {prop.symbol} @ {fill:.2f}", f"Stop {stop:.2f} · Target {target:.2f}\n{prop.thesis}")
            return True, "executed"

    def approve(self, proposal_id: int) -> tuple[bool, str]:
        with SessionLocal() as db:
            p = db.get(Proposal, proposal_id)
            u = self.settings_row(db)
            if not p or p.status not in ("pending", "idea"):
                return False, "proposal is no longer open"
            if p.status == "idea" and u.mode == "research":
                return False, "research mode: place this trade in your own broker app, or switch to Copilot"
            ok, msg = self.execute(db, p, u)
            db.commit()
            return ok, msg

    def reject(self, proposal_id: int, reason: str = "rejected by you") -> bool:
        with SessionLocal() as db:
            p = db.get(Proposal, proposal_id)
            if not p or p.status not in ("pending", "idea"):
                return False
            p.status, p.status_reason = "rejected", reason
            self.log(db, "user", "no", f"not approved: {reason}", p.symbol)
            db.commit()
            return True

    # ---- managing open trades ----------------------------------------------------------------
    def open_trades(self, db) -> list[Trade]:
        return list(db.scalars(select(Trade).where(Trade.closed_at.is_(None))).all())

    def _close_trade(self, db, t: Trade, px: float, reason: str) -> None:
        t.closed_at, t.exit_price, t.exit_reason = self.market.now(), px, reason
        t.pnl = round((px - t.entry_price) * t.qty, 2)
        r = t.entry_price - t.initial_stop
        t.r_multiple = round((px - t.entry_price) / r, 2) if r > 0 else None
        self.log(db, "exit", "info", f"closed {t.qty} @ {px:.2f} ({reason}), P&L {t.pnl:+,.2f}", t.symbol)
        self.alert(db, "info", f"Closed {t.symbol}: {t.pnl:+,.2f}", f"Reason: {reason}")

    def manage_positions(self) -> None:
        with self.lock, SessionLocal() as db:
            swing = self.settings_row(db).strategy == "swing"
            trades = self.open_trades(db)
            by_sym = {t.symbol: t for t in trades}
            for sym, px, reason in self.broker.sync_exits({t.symbol: t.broker_order_id for t in trades}):
                if t := by_sym.pop(sym, None):
                    self._close_trade(db, t, px, reason)
            now = self.market.now()
            flatten = risk.should_flatten(now, self.session_rules) and not swing
            for t in by_sym.values():
                opened = t.opened_at if t.opened_at.tzinfo else t.opened_at.replace(tzinfo=UTC)
                plan = t.plan or {}
                held_min = (now - opened).total_seconds() / 60
                why = ("15:50 close" if flatten
                       else "tested time stop" if plan.get("max_hold_min") and held_min >= plan["max_hold_min"]
                       else "time stop" if (not swing and not self.session_rules and now - opened > DEMO_TIME_STOP) else None)
                if why:
                    res = self.broker.close(t.symbol)
                    if res.ok:
                        q = self.market.quote(t.symbol)
                        self._close_trade(db, t, res.fill_price or (q.price if q else t.entry_price), why)
                    else:
                        self.alert(db, "critical", f"Could not close {t.symbol}", res.message, dedupe_key=f"close:{t.symbol}")
                    continue
                q = self.market.quote(t.symbol)
                if not q:
                    continue
                t.peak_price = max(t.peak_price or t.entry_price, q.price)
                new_stop = (t.stop if plan.get("trail") == "none"  # the tested variant had no trail: keep it as tested
                            else risk.trail_stop(t.entry_price, t.initial_stop, t.stop, q.price))
                if new_stop > t.stop and self.broker.update_stop(t.symbol, t.broker_order_id, new_stop):
                    t.notes = [*t.notes, {"at": now.isoformat(), "note": f"stop raised {t.stop:.2f} → {new_stop:.2f}"}]
                    t.stop = new_stop
            db.commit()

    # ---- Position keeper ---------------------------------------------------------------------
    def run_keepers(self, force_trade_id: int | None = None) -> None:
        """Ask the Position keeper about every open trade. Agent calls happen outside the lock;
        decisions are applied under it, and can only lower risk (sell, or raise the stop)."""
        interval = self.s.keeper_interval_seconds if self.agents.client else 0
        now = self.market.now()
        with SessionLocal() as db:
            due = []
            for t in self.open_trades(db):
                last = t.keeper_log[-1]["at"] if t.keeper_log else None
                if force_trade_id == t.id or not last or (now - datetime.fromisoformat(last)).total_seconds() >= interval:
                    due.append(t.id)
        for tid in due:
            try:
                self._keep(tid)
            except Exception:
                log.exception("keeper failed for trade %s", tid)

    def _keep(self, trade_id: int) -> None:
        with SessionLocal() as db:
            t = db.get(Trade, trade_id)
            if not t or t.closed_at:
                return
            q = self.market.quote(t.symbol)
            bars = self.market.minute_bars(t.symbol, 240)
            if not q or len(bars) < 2:
                return
            f = features.compute(bars, self.market.daily_bars(t.symbol, 60)).to_dict()
            r = t.entry_price - t.initial_stop
            opened = t.opened_at if t.opened_at.tzinfo else t.opened_at.replace(tzinfo=UTC)
            heads = laya.evaluate(t.symbol, features.compute(bars, self.market.daily_bars(t.symbol, 60)),
                                  self.market.news([t.symbol], 30), self.market.now(), lookback_min=24 * 60).headlines
            payload = {
                "position": {"symbol": t.symbol, "qty": t.qty, "entry": t.entry_price, "stop": t.stop, "initial_stop": t.initial_stop,
                             "target": t.target, "price": q.price, "r_multiple": round((q.price - t.entry_price) / r, 2) if r > 0 else 0,
                             "unrealized": round((q.price - t.entry_price) * t.qty, 2), "minutes_open": int((self.market.now() - opened).total_seconds() // 60)},
                "peak_r": round(((t.peak_price or t.entry_price) - t.entry_price) / r, 2) if r > 0 else 0,
                "features": f,
                "headlines_since_entry": [h for h in heads if h["at"] >= opened.isoformat()],
                "mood": self.mood.level if self.mood else "calm",
                "trail_stop": risk.trail_stop(t.entry_price, t.initial_stop, t.stop, q.price),
            }
        decision, src = self.agents.keeper(payload)
        trace = self.agents.last_trace()
        with self.lock, SessionLocal() as db:
            t = db.get(Trade, trade_id)
            if not t or t.closed_at:
                return
            q = self.market.quote(t.symbol)
            entry = {"at": self.market.now().isoformat(), "action": decision.action, "reason": decision.reason,
                     "confidence": decision.confidence, "by": src, "price": q.price if q else None,
                     "r": payload["position"]["r_multiple"], "skills": trace}
            if decision.action == "tighten" and decision.new_stop and q and t.stop < decision.new_stop < q.price:
                if self.broker.update_stop(t.symbol, t.broker_order_id, decision.new_stop):
                    t.notes = [*t.notes, {"at": entry["at"], "note": f"keeper raised stop {t.stop:.2f} → {decision.new_stop:.2f}"}]
                    entry["new_stop"] = decision.new_stop
                    t.stop = decision.new_stop
            elif decision.action == "tighten":
                entry["action"], entry["reason"] = "hold", f"{decision.reason} (stop change not valid, kept {t.stop:.2f})"
            elif decision.action == "sell":
                res = self.broker.close(t.symbol)
                if res.ok:
                    self._close_trade(db, t, res.fill_price or (q.price if q else t.entry_price), "ai sell")
                    self.log(db, "keeper", "info", f"Position keeper sold: {decision.reason}", t.symbol)
                else:
                    entry["reason"] += f" (sell failed: {res.message})"
            prev = list(t.keeper_log or [])
            if prev and prev[-1]["action"] == "hold" and entry["action"] == "hold":
                entry["checks"] = prev[-1].get("checks", 1) + 1  # merge repeated holds into one line
                prev[-1] = entry
            else:
                prev.append(entry)
            t.keeper_log = prev[-40:]
            db.commit()

    def keep_now(self, trade_id: int) -> None:
        self.run_keepers(force_trade_id=trade_id)

    def set_kill_switch(self, on: bool) -> None:
        with self.lock, SessionLocal() as db:
            u = self.settings_row(db)
            u.kill_switch = on
            if on:
                for p in db.scalars(select(Proposal).where(Proposal.status.in_(["pending", "idea"]))).all():
                    p.status, p.status_reason = "rejected", "kill switch"
                for t in self.open_trades(db):
                    res = self.broker.close(t.symbol)
                    q = self.market.quote(t.symbol)
                    if res.ok:
                        self._close_trade(db, t, res.fill_price or (q.price if q else t.entry_price), "kill switch")
                self.log(db, "kill_switch", "alert", "kill switch ON: all positions closed, trading stopped")
                self.alert(db, "critical", "Kill switch ON", "All positions closed. No new trades until you turn it off.")
            else:
                self.log(db, "kill_switch", "info", "kill switch off: trading resumes")
            db.commit()

    def close_trade_now(self, trade_id: int) -> tuple[bool, str]:
        with self.lock, SessionLocal() as db:
            t = db.get(Trade, trade_id)
            if not t or t.closed_at:
                return False, "trade is not open"
            res = self.broker.close(t.symbol)
            if not res.ok:
                return False, res.message
            q = self.market.quote(t.symbol)
            self._close_trade(db, t, res.fill_price or (q.price if q else t.entry_price), "closed by you")
            db.commit()
            return True, "closed"

    # ---- reviewer, briefing, research --------------------------------------------------------
    def review(self, day: str | None = None) -> Review:
        day = day or self.today_et()
        start = datetime.fromisoformat(day).replace(tzinfo=ET).astimezone(UTC)
        end = start + timedelta(days=1)
        with SessionLocal() as db:
            u = self.settings_row(db)
            trades = db.scalars(select(Trade).where(Trade.opened_at >= start, Trade.opened_at < end)).all()
            closed = [t for t in trades if t.pnl is not None]
            props = db.scalars(select(Proposal).where(Proposal.created_at >= start, Proposal.created_at < end)).all()
            nos = db.scalars(select(DecisionLog).where(DecisionLog.at >= start, DecisionLog.at < end, DecisionLog.outcome == "no",
                                                       DecisionLog.stage != "laya").limit(60)).all()
            wins = [t for t in closed if t.pnl > 0]
            snaps = db.scalars(select(EquitySnapshot).where(EquitySnapshot.at >= start, EquitySnapshot.at < end).order_by(EquitySnapshot.at)).all()
            bench = (snaps[-1].benchmark / snaps[0].benchmark - 1) if len(snaps) > 1 and snaps[0].benchmark else 0.0
            acct_ret = (snaps[-1].equity / snaps[0].equity - 1) if len(snaps) > 1 and snaps[0].equity else 0.0
            stats = {
                "trades": len(closed), "win_rate": len(wins) / len(closed) if closed else 0.0,
                "pnl": round(sum(t.pnl for t in closed), 2),
                "avg_r": round(sum(t.r_multiple or 0 for t in closed) / len(closed), 2) if closed else 0.0,
                "targets_hit": sum(1 for t in closed if t.exit_reason == "target"),
                "stopped_out": sum(1 for t in closed if t.exit_reason == "stop"),
                "account_return_pct": round(acct_ret * 100, 3), "sp500_return_pct": round(bench * 100, 3),
                "proposals": len(props), "rejected_by_user": sum(1 for p in props if p.status == "rejected"),
            }
            score_by_prop = {p.id: p.score for p in props}
            payload = {
                "day": day, "stats": stats,
                "current": {"score_threshold": u.score_threshold, "min_reward_risk": u.min_reward_risk},
                "trades": [{"symbol": t.symbol, "entry": t.entry_price, "exit": t.exit_price, "reason": t.exit_reason,
                            "pnl": t.pnl, "r": t.r_multiple, "score": score_by_prop.get(t.proposal_id)} for t in closed],
                "passed_on": [{"symbol": n.symbol, "stage": n.stage, "reason": n.reason[:200]} for n in nos],
            }
            rep, src = self.agents.reviewer(payload)

            # "Change beats live version?" — replay today's trades under the suggested threshold.
            change = {"score_threshold": rep.suggested_score_threshold, "min_reward_risk": rep.suggested_min_reward_risk}
            applied, verdict = False, "no change suggested"
            if rep.suggested_score_threshold != u.score_threshold:
                new_thr = max(50, min(90, rep.suggested_score_threshold))
                # judge rule changes on the last 10 trading days, not one day (one day is mostly noise)
                window_start = start - timedelta(days=14)
                window = db.scalars(select(Trade).where(Trade.opened_at >= window_start, Trade.opened_at < end,
                                                        Trade.pnl.is_not(None), Trade.exit_reason != "demo restart")).all()
                wprops = {p.id: p.score for p in db.scalars(select(Proposal).where(Proposal.id.in_([t.proposal_id for t in window if t.proposal_id]))).all()}
                scored = [(wprops.get(t.proposal_id) or 0, t.pnl) for t in window]
                live_pnl = sum(p for _, p in scored)
                new_pnl = sum(p for s, p in scored if s >= new_thr)
                if new_thr < u.score_threshold:
                    verdict = "lower threshold can't be tested on today's data (those trades were never taken) — kept live version"
                elif len(scored) < REVIEW_MIN_TRADES:
                    verdict = f"only {len(scored)} trades in the last 10 trading days (need {REVIEW_MIN_TRADES}) — too few to prove the change, kept live version"
                elif new_pnl > live_pnl:
                    applied = True
                    verdict = f"replay: threshold {new_thr} → P&L {new_pnl:+,.2f} vs live {live_pnl:+,.2f}; change applied"
                    u.score_threshold = new_thr
                else:
                    verdict = f"replay: threshold {new_thr} → P&L {new_pnl:+,.2f} vs live {live_pnl:+,.2f}; kept live version"
            review = Review(day=day, stats=stats, summary=rep.summary,
                            lessons=rep.lessons, proposed_change=change, change_applied=applied, change_verdict=verdict)
            db.add(review)
            self.log(db, "reviewer", "info", f"review for {day}: {verdict}")
            db.commit()
            return review

    def briefing(self, language: str, force: bool = False) -> Briefing:
        day = self.today_et()
        with SessionLocal() as db:
            if not force:
                b = db.scalar(select(Briefing).where(Briefing.day == day, Briefing.language == language).order_by(Briefing.id.desc()))
                if b and datetime.now(UTC) - (b.at if b.at.tzinfo else b.at.replace(tzinfo=UTC)) < timedelta(hours=2):
                    return b
            movers = []
            for sym in self.market.universe():
                bars = self.market.minute_bars(sym, 240)
                if len(bars) > 30:
                    f = features.compute(bars, self.market.daily_bars(sym, 30))
                    movers.append({"symbol": sym, "change_day_pct": round(f.change_day_pct, 2), "volume_ratio": round(f.volume_ratio, 1)})
            movers.sort(key=lambda m: abs(m["change_day_pct"]), reverse=True)
            props = db.scalars(select(Proposal).where(Proposal.status.in_(["pending", "idea", "executed"])).order_by(Proposal.id.desc()).limit(5)).all()
            acct = self.broker.account()
            payload = {
                "top_movers": movers[:6],
                "watching": [f"{p.symbol} (score {p.score})" for p in props] if not self.agents.client
                else [f"{p.symbol} (score {p.score}): {p.thesis[:200]}" for p in props],
                "market_headlines": [n.headline for n in self.market.news(None, 8)],
                "account": {"equity": round(acct.equity, 2), "day_pnl": round(acct.equity - acct.last_equity, 2),
                            "open_positions": [p.symbol for p in self.broker.positions()]},
            }
            b = Briefing(day=day, language=language, body=self.agents.briefing(payload, language))
            db.add(b)
            db.commit()
            return b

    def ask(self, question: str, symbol: str | None, proposal_id: int | None, language: str) -> str:
        payload: dict = {}
        if symbol:
            payload = self.stock_context(symbol.upper()) or {"symbol": symbol.upper(), "error": "no data for this symbol"}
            payload.pop("suggested_levels", None)
        if proposal_id:
            with SessionLocal() as db:
                p = db.get(Proposal, proposal_id)
                if p:
                    payload["trade_proposal"] = {"symbol": p.symbol, "score": p.score, "thesis": p.thesis, "analyst": p.analyst,
                                                 "devils_advocate": p.devil, "manager": p.manager, "risk_checks": p.risk_checks,
                                                 "status": p.status, "status_reason": p.status_reason}
        return self.agents.ask(question, payload, language)


def _trade_plan(prop: Proposal) -> dict:
    """The exit rules the backtest validated, so the live trade is managed the way it was tested."""
    btr, mgr = prop.backtest or {}, prop.manager or {}
    tp = btr.get("tuned_plan")
    if not (tp and mgr.get("tuned_by_backtest")):
        return {"expected_r": (btr.get("best") or {}).get("oos", {}).get("exp_r")} if btr else {}
    return {"max_hold_min": tp["max_hold_min"], "trail": tp["trail"], "expected_r": tp["expected_r"],
            "variant": tp["variant"], "setup": btr.get("setup")}
