import requests
import os

# Load API key from environment variable
API_KEY = os.getenv("FINNHUB_API_KEY")

# Get ticker price from Finnhub API
def lookup(symbol):
    symbol = symbol.upper().strip()

    try:
        response = requests.get(
            "https://finnhub.io/api/v1/quote",
            params={"symbol": symbol, "token": API_KEY}
        )
        # Raise for HTTP response errors
        response.raise_for_status()
        quote_data = response.json()
        if not quote_data["c"] or quote_data["c"] <= 0:
            return None
        return {
            "name": symbol.upper(),
            "price": float(quote_data["c"]),
            "symbol": symbol.upper()
        }
    
    except requests.RequestException and KeyError and ValueError as e:
        print(f"Request error: {e}")
    
    return None