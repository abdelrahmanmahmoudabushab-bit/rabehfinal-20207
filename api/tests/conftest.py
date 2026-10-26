import os
import sys
from pathlib import Path

# Isolated database and no external services for every test run
os.environ["DATABASE_URL"] = f"sqlite:///{Path(__file__).parent / 'test.db'}"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["ALPACA_API_KEY"] = ""
os.environ["ALPACA_SECRET_KEY"] = ""
os.environ["SIM_NOW"] = "2026-10-21T15:00:00+00:00"  # fixed simulated clock and history: tests must not depend on the date
os.environ["SIM_HISTORY_END"] = "2026-10-20"
os.environ["BACKTEST_MIN_OOS_T"] = "0"  # the demo market is too thin to clear the production bar; test_backtest covers the bar itself
os.environ["BACKTEST_DEFLATE"] = "0"
os.environ["BACKTEST_WORKERS"] = "0"  # in-process; one test exercises the worker process
sys.path.insert(0, str(Path(__file__).parent.parent))
db_file = Path(__file__).parent / "test.db"
if db_file.exists():
    db_file.unlink()
