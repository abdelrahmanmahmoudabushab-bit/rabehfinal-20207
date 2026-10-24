"""The agent team from the Rahbeh plan. Every agent has its own job, the data it reads, the APIs behind that
data, and the skills (tools) it may call. Plain-code steps are listed too, because they have the final say."""

from dataclasses import dataclass, field

from .skills import SKILLS


@dataclass
class AgentSpec:
    id: str
    name: str
    job: str
    when: str  # from the plan: starter | early add | later (split out) | always
    data: list[str]
    skills: list[str] = field(default_factory=list)
    claude: str = "always"  # always (when a key is set) | full (only with AGENT_TEAM=full) | never (plain code)
    writes: str = ""
    module: str = ""
    plan_no: int | None = None  # number in the plan's agent table

    @property
    def apis(self) -> list[str]:
        seen: list[str] = []
        for s in self.skills:
            for src in SKILLS[s].sources:
                if src not in seen:
                    seen.append(src)
        return seen

    def kind(self, claude_enabled: bool, team_mode: str) -> str:
        if self.claude == "never":
            return "code"
        if claude_enabled and (self.claude == "always" or team_mode == "full"):
            return "claude"
        return "rules"


AGENTS: list[AgentSpec] = [
    AgentSpec("data_checks", "Data checks", "Rejects gaps, impossible jumps, zero volume, stale prices and sources that disagree; pauses the stock and alerts.",
              "always", ["live prices", "minute bars", "second price source"], ["get_quote"], "never", "data OK / pause", "pipeline/checks.py"),
    AgentSpec("scanner", "Scanner", "Finds stocks moving on news or heavy trading and ranks the whole market; only the best reach the paid agents.",
              "starter", ["live prices", "minute bars", "headlines"], ["scan_market", "get_quote"], "never", "ranked shortlist", "pipeline/laya.py", 1),
    AgentSpec("news", "News reader", "Reads headlines and company announcements as they land: bullish or bearish, company or market, already priced in?",
              "later", ["headlines with exact times", "SEC filings"], ["get_headlines", "get_filings", "get_quote"], "full", "news report", plan_no=2),
    AgentSpec("chart", "Chart reader", "Trend, momentum and price patterns; names the setup, support and resistance.",
              "later", ["minute bars", "candles 1m–1D", "indicators"], ["get_indicators", "get_candles", "get_benchmark"], "full", "chart report", plan_no=3),
    AgentSpec("company", "Company checker", "Earnings, debt and company health; flags earnings within two days and red flags in filings.",
              "later", ["fundamentals", "earnings dates & surprises", "analyst ratings", "SEC filings"],
              ["get_fundamentals", "get_earnings", "get_analyst_ratings", "get_filings"], "full", "company report", plan_no=4),
    AgentSpec("mood", "Market mood", "Interest rates, VIX, oil and the economic calendar; says when to be careful (half size) or stop (no new trades).",
              "later", ["VIX", "Fed funds", "10-year yield", "oil", "economic calendar", "S&P 500", "breadth"],
              ["get_market_mood", "get_economic_calendar", "get_benchmark"], "full", "calm / careful / stormy", plan_no=5),
    AgentSpec("halal", "Halal checker", "Screens out banks, alcohol, tobacco, gambling, weapons and heavy debt for users who switch it on.",
              "early add", ["business type", "debt", "cash"], ["check_halal", "get_fundamentals"], "never", "pass / fail", "pipeline/halal.py", 6),
    AgentSpec("analyst", "Analyst", "Combines the specialists' reports into one opinion and a 0–100 score (does their jobs itself until they are split out).",
              "starter", ["the four specialist reports", "reviewer lessons"], ["get_quote", "get_indicators"], "always", "score + thesis", plan_no=7),
    AgentSpec("devil", "Devil's advocate", "Argues against every trade; looks for the evidence the Analyst missed. The objection must be answered or the trade dies.",
              "early add", ["analyst report", "news", "earnings", "market mood"],
              ["get_headlines", "get_earnings", "get_market_mood", "get_indicators", "run_backtest"], "always", "strongest objection", plan_no=8),
    AgentSpec("manager", "Manager", "Final call and position size: answers the objection, sets entry, stop and target, and checks the plan with the risk engine.",
              "starter", ["analyst report", "objection", "account", "indicators"],
              ["get_indicators", "risk_check", "get_account", "run_backtest"], "always", "trade plan", plan_no=9),
    AgentSpec("backtester", "Backtester", "Tests every trade the team finds 1,000+ ways on history (setup x filters x exits), judges the best on data it never saw, resamples it 1,000 times, and blocks trades with no proven edge.",
              "always", ["5-minute history of the stock and its peers"], ["run_backtest"], "never", "edge / no edge + tested exits", "backtest/"),
    AgentSpec("keeper", "Position keeper", "Watches every open trade and decides: hold, raise the stop, or sell now. Can only lower risk, never add to it.",
              "added", ["open position", "live price", "indicators", "headlines", "market mood"],
              ["get_position", "get_indicators", "get_candles", "get_headlines", "get_market_mood"], "always", "hold / tighten / sell"),
    AgentSpec("risk", "Risk engine", "Plain code with the final say: 1% risk cap, daily loss stop, exposure limits, earnings blackout, market mood, kill switch.",
              "always", ["trade plan", "account", "positions", "market mood", "earnings date"], ["risk_check", "get_account"], "never",
              "approved size / block", "pipeline/risk.py"),
    AgentSpec("broker", "Order placer", "Sends bracket orders (entry, stop, target), raises stops, closes everything by 15:50 ET.",
              "always", ["approved order"], ["get_account"], "never", "fills", "broker/"),
    AgentSpec("reviewer", "Reviewer", "After the close, grades every trade, writes lessons for the agents, and changes a rule only if it beats the live version.",
              "starter", ["closed trades", "every 'no'", "S&P 500"], ["get_recent_trades", "get_decision_log", "get_benchmark"], "always",
              "lessons + rule change", plan_no=10),
    AgentSpec("coach", "Coach", "Explains trades to users in Arabic or English and answers questions (the AI button).",
              "later", ["anything on screen"], ["get_quote", "get_indicators", "get_headlines", "get_earnings", "get_position", "get_market_mood"],
              "always", "answers + daily briefing", plan_no=11),
]

BY_ID = {a.id: a for a in AGENTS}
