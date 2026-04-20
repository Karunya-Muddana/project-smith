"""
Technical Indicators Tool
Calculates RSI, MACD, and SMAs using yfinance and pandas-ta.
"""

import pandas as pd
import yfinance as yf
# We will use pandas to calculate without strict pandas-ta dependency
# as we can write pure pandas versions of simple TA for reliability.

def calculate_rsi(prices: pd.Series, window: int = 14) -> pd.Series:
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_macd(prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    exp1 = prices.ewm(span=fast, adjust=False).mean()
    exp2 = prices.ewm(span=slow, adjust=False).mean()
    macd = exp1 - exp2
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    histogram = macd - signal_line
    return macd, signal_line, histogram

def run_technical_analysis(ticker: str, period: str = "6mo") -> dict:
    """Main router for TA."""
    if not ticker:
        return {"status": "error", "error": "Ticker required"}
        
    try:
        t = yf.Ticker(ticker)
        df = t.history(period=period)
        
        if df.empty:
            return {"status": "error", "error": f"No price data found for {ticker}"}
            
        close = df['Close']
        
        # Calculate indicators
        rsi = calculate_rsi(close)
        macd, macd_signal, macd_hist = calculate_macd(close)
        sma_20 = close.rolling(window=20).mean()
        sma_50 = close.rolling(window=50).mean()
        sma_200 = close.rolling(window=200).mean()
        
        # Get latest values
        latest_rsi = rsi.iloc[-1]
        latest_macd = macd.iloc[-1]
        latest_macd_signal = macd_signal.iloc[-1]
        
        # Simple signals
        trend_short = "BULLISH" if close.iloc[-1] > sma_20.iloc[-1] else "BEARISH"
        trend_med = "BULLISH" if close.iloc[-1] > sma_50.iloc[-1] else "BEARISH"
        trend_long = "BULLISH" if close.iloc[-1] > sma_200.iloc[-1] else "BEARISH"
        
        rsi_status = "OVERSOLD" if latest_rsi < 30 else ("OVERBOUGHT" if latest_rsi > 70 else "NEUTRAL")
        macd_status = "BULLISH_CROSS" if latest_macd > latest_macd_signal else "BEARISH_CROSS"
        
        return {
            "status": "success",
            "ticker": ticker.upper(),
            "latest_close": round(close.iloc[-1], 2),
            "indicators": {
                "RSI_14": {
                    "value": round(latest_rsi, 2),
                    "status": rsi_status
                },
                "MACD": {
                    "value": round(latest_macd, 2),
                    "signal_line": round(latest_macd_signal, 2),
                    "status": macd_status
                },
                "SMA": {
                    "SMA_20": round(sma_20.iloc[-1], 2) if pd.notna(sma_20.iloc[-1]) else None,
                    "SMA_50": round(sma_50.iloc[-1], 2) if pd.notna(sma_50.iloc[-1]) else None,
                    "SMA_200": round(sma_200.iloc[-1], 2) if pd.notna(sma_200.iloc[-1]) else None
                },
                "trends": {
                    "short_term": trend_short,
                    "medium_term": trend_med,
                    "long_term": trend_long
                }
            }
        }
        
    except Exception as e:
        return {"status": "error", "error": str(e)}

METADATA = {
    "name": "technical_indicators",
    "description": "Calculate stock technical indicators (RSI, MACD, SMA) and determine current trend signals.",
    "function": "run_technical_analysis",
    "dangerous": False,
    "domain": "data",
    "output_type": "structured",
    "parameters": {
        "type": "object",
        "properties": {
            "ticker": {
                "type": "string",
                "description": "Stock ticker symbol (e.g. AAPL, NVDA)"
            },
            "period": {
                "type": "string",
                "enum": ["1mo", "3mo", "6mo", "1y", "2y", "5y"],
                "default": "6mo",
                "description": "Time period to fetch data for (needed for 200 SMA)"
            }
        },
        "required": ["ticker"]
    }
}
