"""The Claude agents: Analyst (scanner + news/chart/company reading), Devil's advocate, Manager,
Reviewer, plus the daily briefing and research Q&A.

Every agent returns validated structured output. Every call is logged to agent_calls (tokens,
latency, errors). Without ANTHROPIC_API_KEY each agent falls back to a transparent heuristic so
the app still works end to end — proposals say which one produced them.
"""

import json
import logging
import time
from typing import Literal, TypeVar

import anthropic
from pydantic import BaseModel

from ..config import Settings
from ..db import AgentCall, SessionLocal

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


# ---- structured outputs ----------------------------------------------------------------
class AnalystReport(BaseModel):
    score: int  # 0-100 conviction that a long day trade works today
    direction: Literal["long", "skip"]
    thesis: str
    news_view: str
    chart_view: str
    company_view: str
    bullish_points: list[str]
    risks: list[str]


class DevilReport(BaseModel):
    objection: str
    severity: int  # 1 (minor) - 5 (deal breaker)
    deal_breaker: bool
    what_would_change_my_mind: str


class ManagerDecision(BaseModel):
    decision: Literal["trade", "pass"]
    objection_answered: bool
    rebuttal: str
    entry: float
    stop: float
    target: float
    confidence: int
    exit_plan: str


class ReviewerReport(BaseModel):
    summary: str
    lessons: list[str]
    suggested_score_threshold: int
    suggested_min_reward_risk: float
    reasoning: str


SYSTEM = """You are part of Rahbeh, a team of AI agents that helps retail investors find and manage
long-only US stock day trades. Positions are closed by 15:50 ET; there is no shorting.

Ground rules for every agent:
- Use only the data given in the message. Never invent prices, news, or numbers.
- Official company announcements and filings outrank articles; social chatter is a weak signal.
- Plain, specific language a non-professional can follow. No hype, no guarantees.
- A separate plain-code risk engine sizes and approves every trade; you cannot override it.
- When the evidence is thin or mixed, say so and lean towards not trading."""

ROLE = {
    "analyst": """Role: Analyst. Combine the news, the chart features and the company basics into one opinion
on whether this stock is a good long day trade right now. Score 0-100 where 65+ means "worth trading".
direction must be "skip" when the setup is weak, bearish, or unclear.""",
    "devil": """Role: Devil's advocate. Make the strongest honest case AGAINST taking this trade.
Pick the single most important objection. severity: 1 minor ... 5 deal breaker. Set deal_breaker only
for problems no stop-loss can fix (e.g. earnings tonight, news already fully priced in, data that doesn't add up).""",
    "manager": """Role: Manager. Read the analyst report and the devil's advocate objection and make the final call.
objection_answered is true only if you can rebut the objection with the data. If you trade, set entry near the
current price, a stop-loss below a real level (VWAP, recent low, or ~1.5-2 ATR), and a target at least 1.5x the
risk away. The suggested levels are computed from the chart; use or adjust them.""",
    "reviewer": """Role: Reviewer. After the close, grade today's trades and the trades we passed on. Find concrete
mistakes and repeatable lessons (max 5, each one sentence an agent can act on). Suggest a score threshold (50-90)
and minimum reward/risk (1.0-4.0) for tomorrow; suggest keeping the current values unless the data clearly says otherwise.""",
}


class Agents:
    def __init__(self, s: Settings):
        self.s = s
        self.client = anthropic.Anthropic(api_key=s.anthropic_api_key, max_retries=2) if s.claude_enabled else None

    @property
    def source(self) -> str:
        return "claude" if self.client else "heuristic"

    # ---- Claude plumbing ------------------------------------------------------------------
    def _parse(self, agent: str, symbol: str | None, payload: dict, schema: type[T]) -> T:
        assert self.client is not None
        started = time.monotonic()
        rec = AgentCall(agent=agent, symbol=symbol, model=self.s.claude_model)
        try:
            resp = self.client.beta.messages.parse(
                model=self.s.claude_model,
                max_tokens=16000,
                system=[
                    {"type": "text", "text": SYSTEM},
                    {"type": "text", "text": ROLE[agent], "cache_control": {"type": "ephemeral"}},
                ],
                messages=[{"role": "user", "content": json.dumps(payload, default=str, indent=1)}],
                output_format=schema,
                output_config={"effort": self.s.agent_effort},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
            rec.input_tokens = resp.usage.input_tokens
            rec.output_tokens = resp.usage.output_tokens
            rec.cache_read_tokens = resp.usage.cache_read_input_tokens or 0
            if resp.stop_reason == "refusal":
                raise RuntimeError("model declined the request")
            if resp.stop_reason == "max_tokens" or resp.parsed_output is None:
                raise RuntimeError(f"no structured output (stop_reason={resp.stop_reason})")
            return resp.parsed_output
        except Exception as e:
            rec.ok, rec.error = False, f"{type(e).__name__}: {e}"[:500]
            raise
        finally:
            rec.latency_ms = int((time.monotonic() - started) * 1000)
            with SessionLocal() as db:
                db.add(rec)
                db.commit()

    def _text(self, agent: str, system: str, prompt: str) -> str:
        assert self.client is not None
        started = time.monotonic()
        rec = AgentCall(agent=agent, model=self.s.claude_model)
        try:
            resp = self.client.beta.messages.create(
                model=self.s.claude_model, max_tokens=16000,
                system=[{"type": "text", "text": SYSTEM}, {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": prompt}],
                output_config={"effort": "low"},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            )
            rec.input_tokens, rec.output_tokens = resp.usage.input_tokens, resp.usage.output_tokens
            if resp.stop_reason == "refusal":
                raise RuntimeError("model declined the request")
            return "".join(b.text for b in resp.content if b.type == "text").strip()
        except Exception as e:
            rec.ok, rec.error = False, f"{type(e).__name__}: {e}"[:500]
            raise
        finally:
            rec.latency_ms = int((time.monotonic() - started) * 1000)
            with SessionLocal() as db:
                db.add(rec)
                db.commit()

    # ---- agents ---------------------------------------------------------------------------
    def analyst(self, ctx: dict) -> tuple[AnalystReport, str]:
        if self.client:
            try:
                return self._parse("analyst", ctx["symbol"], ctx, AnalystReport), "claude"
            except Exception as e:
                log.warning("analyst fell back to heuristic: %s", e)
        return _heuristic_analyst(ctx), "heuristic"

    def devil(self, ctx: dict, report: AnalystReport) -> tuple[DevilReport, str]:
        if self.client:
            try:
                return self._parse("devil", ctx["symbol"], {**ctx, "analyst_report": report.model_dump()}, DevilReport), "claude"
            except Exception as e:
                log.warning("devil fell back to heuristic: %s", e)
        return _heuristic_devil(ctx, report), "heuristic"

    def manager(self, ctx: dict, report: AnalystReport, devil: DevilReport) -> tuple[ManagerDecision, str]:
        if self.client:
            try:
                payload = {**ctx, "analyst_report": report.model_dump(), "devils_advocate": devil.model_dump()}
                return self._parse("manager", ctx["symbol"], payload, ManagerDecision), "claude"
            except Exception as e:
                log.warning("manager fell back to heuristic: %s", e)
        return _heuristic_manager(ctx, report, devil), "heuristic"

    def reviewer(self, payload: dict) -> tuple[ReviewerReport, str]:
        if self.client:
            try:
                return self._parse("reviewer", None, payload, ReviewerReport), "claude"
            except Exception as e:
                log.warning("reviewer fell back to heuristic: %s", e)
        return _heuristic_reviewer(payload), "heuristic"

    def briefing(self, payload: dict, language: str) -> str:
        lang = "Arabic (Modern Standard, clear and friendly)" if language == "ar" else "English"
        if self.client:
            try:
                return self._text(
                    "briefing",
                    "Role: Coach. Write a short daily market briefing for a retail investor: what moved, what the agents "
                    "are watching and why, and how the account is doing. 120-180 words, 3 short paragraphs, no headings, "
                    "no markdown tables. Mention that this is not financial advice in one short closing line.",
                    f"Write it in {lang}.\n\nData:\n{json.dumps(payload, default=str, indent=1)}",
                )
            except Exception as e:
                log.warning("briefing fell back to template: %s", e)
        return _template_briefing(payload, language)

    def ask(self, question: str, payload: dict, language: str) -> str:
        lang = "Arabic" if language == "ar" else "English"
        if self.client:
            try:
                return self._text(
                    "coach",
                    "Role: Coach. Answer the user's question about a stock or about why the agents made a trade, using only "
                    "the data provided. Be concise (under 200 words), concrete, and honest about uncertainty. Plain text, "
                    "short paragraphs or a few bullets. This is education, not personal financial advice.",
                    f"Answer in {lang}.\n\nQuestion: {question}\n\nData:\n{json.dumps(payload, default=str, indent=1)}",
                )
            except Exception as e:
                log.warning("coach fell back to template: %s", e)
        return _template_answer(question, payload)


# ---- heuristic fallbacks (no API key) ------------------------------------------------------
def suggested_levels(f: dict) -> dict:
    price, atr, vwap = f["price"], max(f["atr14"], f["price"] * 0.001), f["vwap"]
    stop = min(price - 1.5 * atr, vwap - 0.25 * atr) if f["above_vwap"] else price - 2 * atr
    stop = min(max(stop, price * 0.98), price * 0.997)  # keep the stop 0.3%–2% away
    risk = price - stop
    return {"entry": round(price, 2), "stop": round(stop, 2), "target": round(price + 2 * risk, 2)}


def _heuristic_analyst(ctx: dict) -> AnalystReport:
    f, laya = ctx["features"], ctx["laya"]
    score = 50 + f["momentum_score"] * 0.25 + laya["sentiment"] * 20
    score += 5 if f["trend"] == "up" else 0
    score -= 10 if f["rsi14"] > 75 else 0
    score -= 5 if f["volume_ratio"] < 1.2 else 0
    score = int(max(0, min(100, score)))
    heads = laya["headlines"]
    news_view = f"{len(heads)} recent headline(s), average tone {laya['sentiment']:+.2f}: \"{heads[0]['headline']}\"" if heads else "No company-specific news; the move is driven by trading activity."
    chart_view = (f"{f['trend'].capitalize()} trend, {f['change_30m_pct']:+.2f}% in 30 min, RSI {f['rsi14']:.0f}, "
                  f"{'above' if f['above_vwap'] else 'below'} VWAP, volume {f['volume_ratio']:.1f}x normal.")
    co = ctx.get("company") or {}
    company_view = f"{co.get('name', ctx['symbol'])} ({co.get('sector', '?')}), debt/market value {co.get('debt_to_mcap', 0):.0%}." if co else "No company data."
    return AnalystReport(
        score=score, direction="long" if score >= 55 else "skip",
        thesis=f"{ctx['symbol']} is {'moving up on ' + ('news' if heads else 'heavy buying') if f['change_30m_pct'] > 0 else 'active'}; "
               f"momentum score {f['momentum_score']:.0f} with a {f['trend']} trend and volume {f['volume_ratio']:.1f}x normal.",
        news_view=news_view, chart_view=chart_view, company_view=company_view,
        bullish_points=[r for r in laya["reasons"] if "bearish" not in r and "stretched" not in r] or ["positive momentum"],
        risks=["intraday reversals are common after news spikes"] + (["RSI is high — chasing risk"] if f["rsi14"] > 70 else []),
    )


def _heuristic_devil(ctx: dict, report: AnalystReport) -> DevilReport:
    f = ctx["features"]
    objections = []
    if f["rsi14"] > 72:
        objections.append((4, f"RSI {f['rsi14']:.0f} — the stock is stretched; late buyers often get caught in the pullback."))
    if f["volume_ratio"] < 1.3:
        objections.append((3, f"Volume is only {f['volume_ratio']:.1f}x normal; the move lacks conviction."))
    if f["price"] > f["vwap"] + 2.5 * f["atr14"]:
        objections.append((3, "Price is far above VWAP; the risk to a sensible stop is large."))
    if not ctx["laya"]["headlines"]:
        objections.append((2, "No news explains the move; it could be noise."))
    if ctx.get("company", {}).get("next_earnings_soon"):
        objections.append((5, "Earnings are imminent; gap risk overwhelms any intraday edge."))
    if not objections:
        objections.append((2, "Moves after the first hour often fade; the edge here is modest."))
    sev, text = max(objections)
    return DevilReport(objection=text, severity=sev, deal_breaker=sev >= 5,
                       what_would_change_my_mind="A pullback that holds VWAP on lower volume, then a new high.")


def _heuristic_manager(ctx: dict, report: AnalystReport, devil: DevilReport) -> ManagerDecision:
    lv = ctx["suggested_levels"]
    answered = not devil.deal_breaker and (devil.severity <= 3 or report.score >= 75)
    trade = answered and report.direction == "long"
    return ManagerDecision(
        decision="trade" if trade else "pass", objection_answered=answered,
        rebuttal=("The stop below VWAP caps the loss if the objection proves right, and the reward is 2x the risk."
                  if answered else "The objection stands; the setup isn't strong enough to overcome it."),
        entry=lv["entry"], stop=lv["stop"], target=lv["target"], confidence=report.score,
        exit_plan="Bracket order: stop-loss and target held at the broker. Stop moves to breakeven at +1R; all positions closed by 15:50 ET.",
    )


def _heuristic_reviewer(payload: dict) -> ReviewerReport:
    st = payload["stats"]
    lessons = []
    if st["trades"] and st["win_rate"] < 0.4:
        lessons.append("Win rate was low; require stronger volume confirmation before entry.")
    if st["stopped_out"] > st["targets_hit"]:
        lessons.append("More stops than targets; avoid entries far above VWAP.")
    if not st["trades"]:
        lessons.append("No trades taken; check whether the score threshold is too strict for current conditions.")
    lessons = lessons or ["Keep current rules; results were in line with expectations."]
    thr = payload["current"]["score_threshold"] + (3 if st["trades"] and st["win_rate"] < 0.4 else 0)
    return ReviewerReport(
        summary=f"{st['trades']} trades, win rate {st['win_rate']:.0%}, P&L {st['pnl']:+,.2f}.",
        lessons=lessons, suggested_score_threshold=min(90, thr),
        suggested_min_reward_risk=payload["current"]["min_reward_risk"], reasoning="Rule-based adjustment from today's win rate.",
    )


def _template_briefing(p: dict, language: str) -> str:
    movers = ", ".join(f"{m['symbol']} {m['change_day_pct']:+.1f}%" for m in p.get("top_movers", [])[:4]) or "—"
    watching = ", ".join(p.get("watching", [])[:4]) or "nothing yet"
    acct = p.get("account", {})
    if language == "ar":
        return (f"أبرز التحركات اليوم: {movers}.\n\nيراقب الوكلاء حاليًا: {watching}.\n\n"
                f"قيمة الحساب {acct.get('equity', 0):,.0f} دولار، وربح/خسارة اليوم {acct.get('day_pnl', 0):+,.0f} دولار. "
                "هذه معلومات تعليمية وليست نصيحة مالية.")
    return (f"Today's biggest moves: {movers}.\n\nThe agents are watching: {watching}.\n\n"
            f"Your account is at ${acct.get('equity', 0):,.0f}, {acct.get('day_pnl', 0):+,.0f} today. "
            "This is education, not financial advice.")


def _template_answer(question: str, p: dict) -> str:
    if p.get("symbol"):
        f = p.get("features") or {}
        return (f"{p['symbol']} is at {f.get('price', 0):.2f} ({f.get('change_day_pct', 0):+.2f}% today), trend "
                f"{f.get('trend', '?')}, RSI {f.get('rsi14', 0):.0f}, volume {f.get('volume_ratio', 0):.1f}x normal. "
                "Add an Anthropic API key for full written answers from the Coach agent.")
    return "Add an Anthropic API key to enable the Coach agent's written answers. Pick a stock to see its live numbers."
