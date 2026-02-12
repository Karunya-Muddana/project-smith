"""
Finance Fetcher Tool
Provides stock price, history, and summary fundamentals using yfinance.
"""

import yfinance as yf

# ------------------------------
# Core Functions
# ------------------------------


def get_stock_price(symbol: str):
    try:
        ticker = yf.Ticker(symbol)
        try:
            price = ticker.fast_info.last_price
        except:
            data = ticker.history(period="1d")
            if data.empty:
                return {"status": "error", "error": "no data"}
            price = data.iloc[-1]["Close"]

        return {
            "status": "success",
            "symbol": symbol.upper(),
            "price": float(round(price, 2)),
            "currency": "USD",
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def get_stock_history(symbol: str, period: str = "1mo", interval: str = "1d"):
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period, interval=interval)
        if hist.empty:
            return {"status": "error", "error": "no data"}
        hist_records = [
            {"date": str(idx)[:10], "close": round(r["Close"], 2)}
            for idx, r in hist.iterrows()
        ]
        return {"status": "success", "symbol": symbol.upper(), "history": hist_records}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def get_stock_summary(symbol: str):
    try:
        ticker = yf.Ticker(symbol)
        return {"status": "success", "symbol": symbol.upper(), "summary": ticker.info}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ===========================================================================
# SMITH AGENT INTERFACE
# ===========================================================================


def run_finance_tool(
    operation: str = "price",
    symbol: str = "",
    period: str = "1mo",
    interval: str = "1d",
):
    # Handle case where AI puts symbol in operation arg by mistake
    if operation not in ["price", "history", "summary"] and not symbol:
        symbol = operation
        operation = "price"

    if not symbol:
        return {"status": "error", "error": "Symbol required."}

    if operation == "price":
        return get_stock_price(symbol)
    elif operation == "history":
        return get_stock_history(symbol, period, interval)
    elif operation == "summary":
        return get_stock_summary(symbol)
    return {"status": "error", "error": f"Unknown operation: {operation}"}


# --- ALIASES (The Anti-Hallucination Fix) ---
finance_fetcher = run_finance_tool
price = run_finance_tool
history = run_finance_tool
summary = run_finance_tool
# --------------------------------------------

METADATA = {
    "name": "finance_fetcher",
    "description": "Get stock data. Use operation='price' for current value.",
    "function": "run_finance_tool",
    "dangerous": False,
    "domain": "data",
    "output_type": "numeric",
    "parameters": {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": ["price", "history", "summary"]},
            "symbol": {"type": "string"},
            "period": {"type": "string", "default": "1mo"},
        },
        "required": ["symbol"],
    },
}
