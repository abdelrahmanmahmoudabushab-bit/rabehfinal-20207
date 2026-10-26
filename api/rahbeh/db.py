"""Database models. SQLite by default; set DATABASE_URL to a Postgres URL for production."""

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
    create_engine,
    event,
    inspect,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .config import get_settings


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """Every timestamp is stored as UTC and read back timezone-aware.

    SQLite has no time zones: it compares timestamps as text and silently drops the offset of an aware value,
    so a New York midnight would be compared as if it were UTC (4–5 hours off). Normalising here makes that
    whole class of bug impossible."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class Base(DeclarativeBase):
    pass


class UserSettings(Base):
    """One row: the user's mode, limits and preferences. Hard caps live in risk.py."""

    __tablename__ = "user_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    mode: Mapped[str] = mapped_column(String(16), default="copilot")  # research | copilot | autopilot
    risk_per_trade_pct: Mapped[float] = mapped_column(Float, default=0.5)
    daily_loss_limit_pct: Mapped[float] = mapped_column(Float, default=2.0)
    max_position_pct: Mapped[float] = mapped_column(Float, default=20.0)
    max_sector_pct: Mapped[float] = mapped_column(Float, default=40.0)
    max_open_positions: Mapped[int] = mapped_column(Integer, default=4)
    max_trades_per_day: Mapped[int] = mapped_column(Integer, default=6)
    min_reward_risk: Mapped[float] = mapped_column(Float, default=1.5)
    score_threshold: Mapped[int] = mapped_column(Integer, default=65)
    halal_only: Mapped[bool] = mapped_column(Boolean, default=False)
    allowed_symbols: Mapped[list] = mapped_column(JSON, default=list)  # empty = any
    strategy: Mapped[str] = mapped_column(String(32), default="day_momentum")
    language: Mapped[str] = mapped_column(String(4), default="en")
    kill_switch: Mapped[bool] = mapped_column(Boolean, default=False)
    autopilot_unlocked: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class Proposal(Base):
    """A trade idea that came out of the agent pipeline, with its full reasoning."""

    __tablename__ = "proposals"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    side: Mapped[str] = mapped_column(String(8), default="buy")
    score: Mapped[int] = mapped_column(Integer)
    entry: Mapped[float] = mapped_column(Float)
    stop: Mapped[float] = mapped_column(Float)
    target: Mapped[float] = mapped_column(Float)
    qty: Mapped[int] = mapped_column(Integer, default=0)
    risk_amount: Mapped[float] = mapped_column(Float, default=0)
    thesis: Mapped[str] = mapped_column(Text)
    analyst: Mapped[dict] = mapped_column(JSON)
    devil: Mapped[dict] = mapped_column(JSON)
    manager: Mapped[dict] = mapped_column(JSON)
    features: Mapped[dict] = mapped_column(JSON)
    risk_checks: Mapped[list] = mapped_column(JSON, default=list)
    # idea (research mode) | pending (copilot) | executed | rejected | expired | blocked
    status: Mapped[str] = mapped_column(String(16), index=True)
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_source: Mapped[str] = mapped_column(String(16), default="claude")  # claude | heuristic
    team: Mapped[dict] = mapped_column(JSON, default=dict)  # specialist reports: news, chart, company, mood
    backtest: Mapped[dict] = mapped_column(JSON, default=dict)  # the 1,000+ variant test of this setup


class Trade(Base):
    __tablename__ = "trades"
    id: Mapped[int] = mapped_column(primary_key=True)
    proposal_id: Mapped[int | None] = mapped_column(ForeignKey("proposals.id"), nullable=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    sector: Mapped[str] = mapped_column(String(64), default="")
    qty: Mapped[int] = mapped_column(Integer)
    entry_price: Mapped[float] = mapped_column(Float)
    initial_stop: Mapped[float] = mapped_column(Float)
    stop: Mapped[float] = mapped_column(Float)
    target: Mapped[float] = mapped_column(Float)
    opened_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    r_multiple: Mapped[float | None] = mapped_column(Float, nullable=True)
    broker_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mode: Mapped[str] = mapped_column(String(16), default="copilot")
    notes: Mapped[list] = mapped_column(JSON, default=list)  # stop raises etc.
    sim: Mapped[bool] = mapped_column(Boolean, default=False)  # simulated (demo) trade: never counts toward unlocking live Autopilot
    origin: Mapped[str] = mapped_column(String(16), default="scanner")  # scanner | deal_finder | chart
    peak_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    keeper_log: Mapped[list] = mapped_column(JSON, default=list)  # Position keeper verdicts, newest last
    plan: Mapped[dict] = mapped_column(JSON, default=dict)  # tested exit rules: max_hold_min, trail, expected_r, variant


class DecisionLog(Base):
    """Every 'no' in the pipeline, plus other notable decisions."""

    __tablename__ = "decision_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    symbol: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    stage: Mapped[str] = mapped_column(String(32), index=True)
    outcome: Mapped[str] = mapped_column(String(16))  # no | yes | info | alert
    reason: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class AgentCall(Base):
    """Tracking for every Claude call: tokens, latency, outcome."""

    __tablename__ = "agent_calls"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    agent: Mapped[str] = mapped_column(String(32))
    symbol: Mapped[str | None] = mapped_column(String(16), nullable=True)
    model: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    skills: Mapped[list] = mapped_column(JSON, default=list)  # tools the agent called: [{skill, args, summary}]


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    day: Mapped[str] = mapped_column(String(10), index=True)
    stats: Mapped[dict] = mapped_column(JSON)
    summary: Mapped[str] = mapped_column(Text)
    lessons: Mapped[list] = mapped_column(JSON, default=list)
    proposed_change: Mapped[dict] = mapped_column(JSON, default=dict)
    change_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    change_verdict: Mapped[str] = mapped_column(Text, default="")


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    equity: Mapped[float] = mapped_column(Float)
    benchmark: Mapped[float] = mapped_column(Float)  # SPY price at the same moment


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    level: Mapped[str] = mapped_column(String(8))  # info | warn | critical
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    read: Mapped[bool] = mapped_column(Boolean, default=False)


class StoredBar(Base):
    """Our own copy of every minute bar the pipeline used, so any decision can be replayed."""

    __tablename__ = "bars"
    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime(), primary_key=True)
    o: Mapped[float] = mapped_column(Float)
    h: Mapped[float] = mapped_column(Float)
    l: Mapped[float] = mapped_column(Float)  # noqa: E741
    c: Mapped[float] = mapped_column(Float)
    v: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(16))


class Shadow(Base):
    """Rules vs Claude A/B: both scored the same stock at the same moment; forward returns are filled in later."""

    __tablename__ = "shadow_scores"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    symbol: Mapped[str] = mapped_column(String(16))
    price: Mapped[float] = mapped_column(Float)
    threshold: Mapped[int] = mapped_column(Integer)
    claude_score: Mapped[int] = mapped_column(Integer)
    claude_go: Mapped[bool] = mapped_column(Boolean)
    rules_score: Mapped[int] = mapped_column(Integer)
    rules_go: Mapped[bool] = mapped_column(Boolean)
    fwd_30: Mapped[float | None] = mapped_column(Float, nullable=True)  # % change 30 min later
    fwd_60: Mapped[float | None] = mapped_column(Float, nullable=True)


class HistBar(Base):
    """Cached history for the backtester (our own copy, so any backtest can be replayed)."""

    __tablename__ = "hist_bars"
    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    tf: Mapped[str] = mapped_column(String(4), primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime(), primary_key=True)
    o: Mapped[float] = mapped_column(Float)
    h: Mapped[float] = mapped_column(Float)
    l: Mapped[float] = mapped_column(Float)  # noqa: E741
    c: Mapped[float] = mapped_column(Float)
    v: Mapped[float] = mapped_column(Float)


class Briefing(Base):
    __tablename__ = "briefings"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    day: Mapped[str] = mapped_column(String(10), index=True)
    language: Mapped[str] = mapped_column(String(4))
    body: Mapped[str] = mapped_column(Text)


_settings = get_settings()
_sqlite = _settings.database_url.startswith("sqlite")
engine = create_engine(
    _settings.database_url,
    connect_args={"check_same_thread": False, "timeout": 30} if _sqlite else {},
)

if _sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        # WAL lets the scanner, the deal finder and API requests read while another thread writes
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)
    _add_missing_columns()
    with SessionLocal() as s:
        if s.get(UserSettings, 1) is None:
            s.add(UserSettings(id=1))
            s.commit()


def _add_missing_columns() -> None:
    """Tiny forward-only migration: add columns that newer versions introduced to existing tables."""
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have:
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(engine.dialect)}'))
