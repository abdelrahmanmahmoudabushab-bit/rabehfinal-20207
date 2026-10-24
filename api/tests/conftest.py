import os
import sys
from pathlib import Path

# Isolated database and no external services for every test run
os.environ["DATABASE_URL"] = f"sqlite:///{Path(__file__).parent / 'test.db'}"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["ALPACA_API_KEY"] = ""
os.environ["ALPACA_SECRET_KEY"] = ""
sys.path.insert(0, str(Path(__file__).parent.parent))
db_file = Path(__file__).parent / "test.db"
if db_file.exists():
    db_file.unlink()
