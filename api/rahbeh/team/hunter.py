"""Deal finder: the agent team hunts the whole market for the single best long trade right now.

Scanner ranks every stock -> the top few get the full specialist team + Analyst -> the best goes to the
Devil's advocate, Manager and risk engine (next best if it fails) -> one deal waits for the user's approval
and chosen size. Every hand-off is recorded as a step, so the page can show the team working live.
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ..db import Proposal, SessionLocal
from ..market.universe import FUNDAMENTALS, sector_of
from ..pipeline import halal, risk
from . import skills

if TYPE_CHECKING:
    from ..engine import Engine

log = logging.getLogger(__name__)
MAX_FINALISTS = 3


@dataclass
class Hunt:
    id: str
    started_at: str
    status: str = "running"  # running | found | no_deal | failed
    steps: list[dict] = field(default_factory=list)
    ranking: list[dict] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)
    deal: dict | None = None
    proposal_id: int | None = None
    trade_id: int | None = None
    finished_at: str | None = None
    message: str = ""

    def step(self, agent: str, text: str, symbol: str | None = None, by: str = "code", skills_used: list | None = None, ok: bool | None = None):
        self.steps.append({"at": datetime.now(UTC).isoformat(), "agent": agent, "symbol": symbol, "text": text, "by": by,
                           "skills": skills_used or [], "ok": ok})

    def to_dict(self) -> dict:
        return asdict(self)


def start(engine: Engine) -> Hunt:
    with engine._hunt_lock:
        running = [h for h in engine.hunts.values() if h.status == "running"]
        if running:
            return running[0]
        h = Hunt(id=uuid.uuid4().hex[:10], started_at=datetime.now(UTC).isoformat())
        engine.hunts[h.id] = h
        engine.latest_hunt_id = h.id
    threading.Thread(target=_run, args=(engine, h), daemon=True, name=f"hunt-{h.id}").start()
    return h


def _run(e: Engine, h: Hunt) -> None:
    try:
        _hunt(e, h)
    except Exception as err:
        log.exception("hunt failed")
        h.status, h.message = "failed", f"{type(err).__name__}: {err}"
        h.step("system", f"Hunt failed: {err}", ok=False)
    finally:
        h.finished_at = datetime.now(UTC).isoformat()


def _hunt(e: Engine, h: Hunt) -> None:
    with SessionLocal() as db:
        u = e.settings_row(db)
        halal_only, threshold, mode = u.halal_only, u.score_threshold, u.mode
        kill = u.kill_switch
    if kill:
        h.status, h.message = "no_deal", "Kill switch is on."
        h.step("risk", "Kill switch is on — no hunting.", ok=False)
        return

    # 1. Market mood first: no point hunting in a storm
    if e.mood is None:
        e.update_mood()
    m = e.mood
    h.step("mood", f"Market is {m.level}: {'; '.join(m.reasons)}." + (" Size will be halved." if m.level == "careful" else ""),
           by="code", skills_used=[{"skill": "get_market_mood", "summary": m.level}], ok=m.level != "stormy")
    if m.level == "stormy":
        h.status, h.message = "no_deal", "Market mood is stormy: no new trades."
        return

    # 2. Scanner ranks the whole market
    ranking, summary = skills.call(e, "scan_market", {"limit": 30})
    held = {p.symbol for p in e.broker.positions()}
    h.ranking = ranking
    h.step("scanner", f"Ranked {len(ranking)} stocks by momentum, volume, news tone and trend. Top: "
           + ", ".join(f"{r['symbol']} ({r['score']:.0f})" for r in ranking[:5]), by="code",
           skills_used=[{"skill": "scan_market", "summary": summary}], ok=True)

    shortlist = []
    for r in ranking:
        sym = r["symbol"]
        if sym in held:
            h.step("scanner", "Already holding — skipped.", sym, ok=False)
            continue
        if r["trend"] == "down" or r["news_sentiment"] < -0.15:
            continue
        if halal_only:
            hr = halal.screen(e.market.fundamentals(sym))
            if not hr.passes:
                h.step("halal", f"Not halal: {'; '.join(hr.reasons)}", sym, skills_used=[{"skill": "check_halal", "summary": "fail"}], ok=False)
                continue
        shortlist.append(sym)
        if len(shortlist) >= e.s.hunt_depth:
            break
    if not shortlist:
        h.status, h.message = "no_deal", "Nothing in the market looks like a long trade right now."
        h.step("scanner", h.message, ok=False)
        return
    h.step("scanner", f"Shortlist for the specialists: {', '.join(shortlist)}.", ok=True)

    # 3. Specialists + Analyst on each shortlisted stock
    lessons = e._latest_lessons_safe()
    contexts: dict[str, dict] = {}
    for sym in shortlist:
        ctx = e.stock_context(sym)
        if not ctx:
            continue
        ctx["lessons_from_reviewer"] = lessons
        team = e.agents.team(ctx)
        team["mood"] = {**e.mood_report, "level": m.level}
        ctx["team_reports"] = team
        for k, label in (("news", "news"), ("chart", "chart"), ("company", "company")):
            rpt = team[k]
            h.step(label, rpt["summary"], sym, by=rpt["by"], skills_used=rpt.get("skills"),
                   ok=not (k == "company" and rpt.get("earnings_risk")))
        rep, src = e.agents.analyst(ctx)
        h.step("analyst", f"Score {rep.score}/100 — {rep.thesis}", sym, by=src, skills_used=e.agents.last_trace(),
               ok=rep.direction == "long" and rep.score >= threshold)
        contexts[sym] = ctx
        h.candidates.append({"symbol": sym, "name": FUNDAMENTALS[sym].name if sym in FUNDAMENTALS else sym, "score": rep.score,
                             "direction": rep.direction, "thesis": rep.thesis, "analyst": rep.model_dump(), "team": team,
                             "price": ctx["features"]["price"], "change_day_pct": round(ctx["features"]["change_day_pct"], 2)})

    finalists = sorted((c for c in h.candidates if c["direction"] == "long" and c["score"] >= threshold),
                       key=lambda c: c["score"], reverse=True)[:MAX_FINALISTS]
    if not finalists:
        best = max(h.candidates, key=lambda c: c["score"], default=None)
        h.status = "no_deal"
        h.message = f"No stock cleared the score line of {threshold}" + (f" (best: {best['symbol']} at {best['score']})." if best else ".")
        h.step("analyst", h.message, ok=False)
        return

    # 4. Devil's advocate -> Manager -> risk engine, best first
    from ..pipeline.agents import AnalystReport

    for c in finalists:
        sym, ctx = c["symbol"], contexts[c["symbol"]]
        rep = AnalystReport(**c["analyst"])
        dv, src = e.agents.devil(ctx, rep)
        h.step("devil", f"({dv.severity}/5) {dv.objection}", sym, by=src, skills_used=e.agents.last_trace(), ok=not dv.deal_breaker)
        mg, src = e.agents.manager(ctx, rep, dv)
        h.step("manager", ("Take it. " if mg.decision == "trade" else "Pass. ") + mg.rebuttal, sym, by=src,
               skills_used=e.agents.last_trace(), ok=mg.decision == "trade" and mg.objection_answered)
        if mg.decision != "trade" or not mg.objection_answered:
            continue
        with SessionLocal() as db:
            u = e.settings_row(db)
            days = ctx["earnings"]["days_until"]
            rd = risk.evaluate(risk.TradeRequest(sym, sector_of(sym), mg.entry, mg.stop, mg.target, days), e.risk_context(db, u), e.limits(u))
            h.step("risk", "Allowed: up to " + f"{rd.qty} shares, risking ${rd.risk_amount:,.0f}" if rd.approved else f"Blocked: {rd.reason}",
                   sym, ok=rd.approved)
            if not rd.approved:
                continue
            prop = Proposal(
                symbol=sym, score=rep.score, entry=mg.entry, stop=mg.stop, target=mg.target, qty=rd.qty,
                risk_amount=rd.risk_amount, thesis=rep.thesis, analyst=rep.model_dump(), devil=dv.model_dump(),
                manager=mg.model_dump(), features={**ctx["features"], "headlines": ctx["laya"]["headlines"]},
                risk_checks=rd.as_list(), status="idea" if mode == "research" else "pending",
                status_reason="deal finder", agent_source=src, created_at=e.market.now(), team=ctx["team_reports"],
            )
            db.add(prop)
            db.flush()
            e.log(db, "deal_finder", "yes", f"best deal: {sym} (score {rep.score}), waiting for approval", sym)
            db.commit()
            per_share = mg.entry - mg.stop
            h.proposal_id = prop.id
            h.deal = {
                "symbol": sym, "name": c["name"], "score": rep.score, "thesis": rep.thesis, "entry": mg.entry, "stop": mg.stop,
                "target": mg.target, "max_qty": rd.qty, "risk_per_share": round(per_share, 4),
                "reward_per_share": round(mg.target - mg.entry, 4), "exit_plan": mg.exit_plan, "devil": dv.model_dump(),
                "manager": mg.model_dump(), "team": ctx["team_reports"], "risk_checks": rd.as_list(), "mood": m.level,
                "earnings": ctx["earnings"],
            }
            h.status, h.message = "found", f"Best deal: {sym}. Choose how many shares and approve to buy."
            h.step("manager", h.message, sym, ok=True)
            return
    h.status, h.message = "no_deal", "The finalists did not survive the devil's advocate, manager and risk checks."
    h.step("risk", h.message, ok=False)


def buy(e: Engine, hunt_id: str, qty: int) -> tuple[bool, str, int | None]:
    h = e.hunts.get(hunt_id)
    if not h or h.status != "found" or not h.proposal_id:
        return False, "this hunt has no deal to buy", None
    with SessionLocal() as db:
        p = db.get(Proposal, h.proposal_id)
        u = e.settings_row(db)
        if not p or p.status not in ("pending", "idea"):
            return False, "the deal is no longer open (it may have expired — hunt again)", None
        ok, msg = e.execute(db, p, u, qty=qty, origin="deal_finder")
        db.commit()
        if not ok:
            return False, msg, None
        from sqlalchemy import select

        from ..db import Trade

        t = db.scalar(select(Trade).where(Trade.proposal_id == p.id))
        h.trade_id = t.id if t else None
        h.status = "bought"
        h.step("broker", f"Bought {qty} {p.symbol}. Bracket order live: stop {p.stop:.2f}, target {p.target:.2f}. "
               "The Position keeper is now watching it.", p.symbol, ok=True)
    return True, "bought", h.trade_id
