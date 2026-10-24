"""Built-in stock universe used by the demo simulator and as metadata for the live feed.

Fundamentals here are rounded, illustrative figures for the demo only. In live mode they
are replaced by Financial Modeling Prep data when FMP_API_KEY is set.
"""

from .base import Fundamentals

B = 1e9

# symbol, name, sector, industry, start price, mcap, revenue, net income, debt, cash, tags
_ROWS = [
    ("AAPL", "Apple", "Technology", "Consumer Electronics", 228, 3400, 395, 97, 104, 65, []),
    ("MSFT", "Microsoft", "Technology", "Software", 430, 3200, 262, 92, 60, 75, []),
    ("NVDA", "NVIDIA", "Technology", "Semiconductors", 135, 3300, 130, 73, 9, 43, []),
    ("AMD", "Advanced Micro Devices", "Technology", "Semiconductors", 160, 260, 26, 2, 2, 5, []),
    ("AVGO", "Broadcom", "Technology", "Semiconductors", 175, 820, 52, 6, 67, 9, []),
    ("CRM", "Salesforce", "Technology", "Software", 290, 280, 37, 6, 11, 14, []),
    ("ADBE", "Adobe", "Technology", "Software", 510, 225, 21, 5, 4, 8, []),
    ("GOOGL", "Alphabet", "Communication", "Internet", 170, 2100, 340, 94, 11, 95, []),
    ("META", "Meta Platforms", "Communication", "Internet", 580, 1450, 156, 55, 29, 70, []),
    ("NFLX", "Netflix", "Communication", "Entertainment", 700, 300, 37, 8, 14, 9, []),
    ("AMZN", "Amazon", "Consumer", "E-commerce", 190, 2000, 620, 49, 58, 88, []),
    ("TSLA", "Tesla", "Consumer", "Autos", 245, 790, 97, 13, 7, 33, []),
    ("COST", "Costco", "Consumer", "Retail", 890, 395, 254, 7, 6, 11, []),
    ("WMT", "Walmart", "Consumer", "Retail", 80, 640, 665, 17, 45, 9, []),
    ("NKE", "Nike", "Consumer", "Apparel", 80, 120, 51, 5, 8, 9, []),
    ("HD", "Home Depot", "Consumer", "Home Improvement", 400, 395, 155, 15, 52, 2, []),
    ("JNJ", "Johnson & Johnson", "Healthcare", "Pharma", 160, 385, 87, 14, 36, 25, []),
    ("UNH", "UnitedHealth", "Healthcare", "Insurance", 560, 520, 390, 20, 77, 30, ["insurance"]),
    ("PFE", "Pfizer", "Healthcare", "Pharma", 29, 165, 60, 4, 61, 12, []),
    ("XOM", "Exxon Mobil", "Energy", "Oil & Gas", 118, 520, 340, 34, 41, 27, []),
    ("CVX", "Chevron", "Energy", "Oil & Gas", 150, 270, 195, 18, 24, 6, []),
    ("JPM", "JPMorgan Chase", "Financials", "Banks", 220, 620, 160, 55, 400, 500, ["conventional_finance"]),
    ("BAC", "Bank of America", "Financials", "Banks", 40, 310, 100, 26, 300, 350, ["conventional_finance"]),
    ("STZ", "Constellation Brands", "Consumer Staples", "Beverages - Alcohol", 245, 45, 10, 1, 12, 0.1, ["alcohol"]),
    ("MO", "Altria", "Consumer Staples", "Tobacco", 52, 90, 24, 11, 25, 3, ["tobacco"]),
    ("LVS", "Las Vegas Sands", "Consumer", "Casinos & Gaming", 48, 35, 11, 1.5, 15, 4, ["gambling"]),
    ("LMT", "Lockheed Martin", "Industrials", "Aerospace & Defense", 550, 130, 71, 6, 17, 2, ["weapons"]),
    ("CAT", "Caterpillar", "Industrials", "Machinery", 370, 180, 66, 11, 38, 6, []),
]

FUNDAMENTALS: dict[str, Fundamentals] = {}
START_PRICES: dict[str, float] = {}
for sym, name, sector, industry, price, mcap, rev, ni, debt, cash, tags in _ROWS:
    FUNDAMENTALS[sym] = Fundamentals(
        symbol=sym, name=name, sector=sector, industry=industry, market_cap=mcap * B,
        revenue=rev * B, net_income=ni * B, total_debt=debt * B, cash=cash * B, business_tags=list(tags),
    )
    START_PRICES[sym] = float(price)

BENCHMARK = "SPY"
START_PRICES[BENCHMARK] = 570.0
SYMBOLS = [r[0] for r in _ROWS]


def sector_of(symbol: str) -> str:
    f = FUNDAMENTALS.get(symbol)
    return f.sector if f else "Unknown"
