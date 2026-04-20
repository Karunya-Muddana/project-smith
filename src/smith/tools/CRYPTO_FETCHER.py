"""
Crypto Fetcher Tool
Queries CoinGecko public API for live cryptocurrency data.
No API Key required. Rate limited by IP.
"""

import urllib.request
import json

def fetch_crypto_price(coin_id: str) -> dict:
    # CoinGecko requires the specific ID (e.g., 'bitcoin', 'ethereum', 'solana')
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd&include_market_cap=true&include_24hr_vol=true&include_24hr_change=true"
    
    req = urllib.request.Request(url, headers={'User-Agent': 'SmithAgent/3.0'})
    
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            
        if coin_id not in data:
            return {"status": "error", "error": f"Coin '{coin_id}' not found. Ensure you are using the full name ID (e.g. 'bitcoin' not 'btc')."}
            
        coin_data = data[coin_id]
        return {
            "status": "success",
            "coin_id": coin_id,
            "price_usd": coin_data.get("usd"),
            "market_cap_usd": coin_data.get("usd_market_cap"),
            "volume_24h_usd": coin_data.get("usd_24h_vol"),
            "change_24h_percent": round(coin_data.get("usd_24h_change", 0), 2)
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}

def fetch_crypto_search(query: str) -> dict:
    url = f"https://api.coingecko.com/api/v3/search?query={query}"
    req = urllib.request.Request(url, headers={'User-Agent': 'SmithAgent/3.0'})
    
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            
        coins = data.get("coins", [])
        if not coins:
            return {"status": "error", "error": f"No coins found matching '{query}'"}
            
        # Return top 3 matches
        results = []
        for c in coins[:3]:
            results.append({
                "id": c.get("id"),
                "name": c.get("name"),
                "symbol": c.get("symbol"),
                "market_cap_rank": c.get("market_cap_rank")
            })
            
        return {
            "status": "success",
            "search_query": query,
            "matches": results
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}

def run_crypto_fetcher(operation: str, query: str = "", coin_id: str = "") -> dict:
    if operation == "search":
        if not query:
            return {"status": "error", "error": "Query required for search"}
        return fetch_crypto_search(query)
    elif operation == "price":
        # Check if they passed a symbol instead of an ID. If short, search first to get the ID.
        if not coin_id:
            coin_id = query
            
        if not coin_id:
             return {"status": "error", "error": "coin_id required for price"}
             
        # Optional: Auto-resolve symbols like "BTC" to "bitcoin"
        if len(coin_id) <= 4:
            search_res = fetch_crypto_search(coin_id)
            if search_res.get("status") == "success" and search_res.get("matches"):
                # Take exact symbol match if available, otherwise first result
                matches = search_res["matches"]
                exact = next((m for m in matches if m["symbol"].lower() == coin_id.lower()), matches[0])
                coin_id = exact["id"]
                
        return fetch_crypto_price(coin_id.lower())
    else:
        return {"status": "error", "error": f"Unknown operation {operation}"}

METADATA = {
    "name": "crypto_fetcher",
    "description": "Fetch live cryptocurrency prices and market data via CoinGecko. Use operation='search' to find a coin ID by name/symbol, or operation='price' to get the live USD price for it.",
    "function": "run_crypto_fetcher",
    "dangerous": False,
    "domain": "data",
    "output_type": "numeric",
    "parameters": {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["search", "price"],
                "description": "Whether to search for a coin or get its price."
            },
            "query": {
                "type": "string",
                "description": "Search term or symbol if operation='search'"
            },
            "coin_id": {
                "type": "string",
                "description": "The exact coin ID (e.g. 'bitcoin', 'ethereum') if operation='price'"
            }
        },
        "required": ["operation"]
    }
}
