"""
WEATHER FETCHER — Open-Meteo Integration
----------------------------------------
Fetches real-time weather data without requiring an API key.
Source: https://open-meteo.com/
"""

import requests

# ------------------------------
# Configuration
# ------------------------------

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

# WMO Weather Codes (Interpretation)
WEATHER_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    80: "Rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}

# ------------------------------
# Core Functions
# ------------------------------


def get_coordinates(city: str):
    """Convert city name to Lat/Lon."""
    try:
        params = {"name": city, "count": 1, "language": "en", "format": "json"}
        resp = requests.get(GEOCODING_URL, params=params, timeout=10)
        resp.raise_for_status()

        data = resp.json()
        if not data.get("results"):
            return None

        location = data["results"][0]
        return {
            "name": location["name"],
            "lat": location["latitude"],
            "lon": location["longitude"],
            "country": location.get("country", ""),
        }
    except Exception as e:
        raise RuntimeError(f"Geocoding failed: {e}")


def get_weather_by_city(city: str):
    """
    Fetches the weather description for a given city.
    """
    try:
        # 1. Resolve Location
        loc = get_coordinates(city)
        if not loc:
            return {"status": "error", "error": f"City '{city}' not found."}

        # 2. Fetch Weather
        params = {
            "latitude": loc["lat"],
            "longitude": loc["lon"],
            "current": [
                "temperature_2m",
                "relative_humidity_2m",
                "weather_code",
                "wind_speed_10m",
            ],
            "timezone": "auto",
        }

        resp = requests.get(WEATHER_URL, params=params, timeout=10)
        resp.raise_for_status()

        data = resp.json()
        current = data.get("current", {})

        # 3. Interpret Code
        code = current.get("weather_code", 0)
        condition = WEATHER_CODES.get(code, "Unknown")

        return {
            "status": "success",
            "city": loc["name"],
            "country": loc["country"],
            "temperature": current.get("temperature_2m"),
            "humidity": current.get("relative_humidity_2m"),
            "wind_speed": current.get("wind_speed_10m"),
            "condition": condition,
            "unit": "Celsius",
        }

    except Exception as e:
        return {"status": "error", "error": str(e)}


# ===========================================================================
# SMITH AGENT INTERFACE (Wrapper)
# ===========================================================================


def run_weather_tool(city: str):
    """
    Dispatcher function for weather.
    """
    return get_weather_by_city(city)


weather_fetcher = run_weather_tool
# ===========================================================================
# METADATA (SMS v1.0)
# ===========================================================================

METADATA = {
    "name": "weather_fetcher",
    "description": (
        "Get the current weather forecast (temperature, condition, wind) for any city globally."
    ),
    "function": "run_weather_tool",
    "dangerous": False,
    "domain": "data",
    "output_type": "numeric",
    "parameters": {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": (
                    "The name of the city (e.g., 'London', 'Tokyo', 'New York')."
                ),
            }
        },
        "required": ["city"],
    },
}

if __name__ == "__main__":
    print(get_weather_by_city("London"))
