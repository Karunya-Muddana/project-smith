"""
NUMERIC COMPUTER — Deterministic Calculations
----------------------------------------------
Performs deterministic mathematical operations on numeric data.
Prevents LLM from fabricating mathematical results.
"""

from typing import List, Dict, Any
import statistics


def calculate_trend(prices: List[float], window: int = None) -> Dict[str, Any]:
    """
    Calculate price trend using linear regression.
    
    Args:
        prices: List of price values (chronological order)
        window: Optional window size for moving average
        
    Returns:
        Dict with trend direction, slope, and metrics
    """
    if not prices or len(prices) < 2:
        return {"status": "error", "error": "Need at least 2 data points"}
    
    try:
        n = len(prices)
        
        # Simple linear regression
        x_vals = list(range(n))
        x_mean = statistics.mean(x_vals)
        y_mean = statistics.mean(prices)
        
        # Calculate slope
        numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_vals, prices))
        denominator = sum((x - x_mean) ** 2 for x in x_vals)
        
        slope = numerator / denominator if denominator != 0 else 0
        
        # Percent change
        first_price = prices[0]
        last_price = prices[-1]
        percent_change = ((last_price - first_price) / first_price) * 100 if first_price != 0 else 0
        
        # Direction
        if slope > 0.01:
            direction = "upward"
        elif slope < -0.01:
            direction = "downward"
        else:
            direction = "flat"
        
        result = {
            "status": "success",
            "direction": direction,
            "slope": round(slope, 4),
            "percent_change": round(percent_change, 2),
            "start_value": round(first_price, 2),
            "end_value": round(last_price, 2),
            "data_points": n
        }
        
        # Moving average if requested
        if window and window > 0 and window <= n:
            moving_avg = []
            for i in range(n - window + 1):
                avg = statistics.mean(prices[i:i + window])
                moving_avg.append(round(avg, 2))
            result["moving_average"] = moving_avg
        
        return result
        
    except Exception as e:
        return {"status": "error", "error": str(e)}


def calculate_percent_change(old_value: float, new_value: float) -> Dict[str, Any]:
    """Calculate percentage change between two values."""
    try:
        if old_value == 0:
            return {"status": "error", "error": "Cannot calculate percent change from zero"}
        
        change = ((new_value - old_value) / old_value) * 100
        
        return {
            "status": "success",
            "percent_change": round(change, 2),
            "absolute_change": round(new_value - old_value, 2),
            "old_value": old_value,
            "new_value": new_value
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def calculate_statistics(values: List[float]) -> Dict[str, Any]:
    """Calculate descriptive statistics for a dataset."""
    try:
        if not values:
            return {"status": "error", "error": "Empty dataset"}
        
        return {
            "status": "success",
            "count": len(values),
            "mean": round(statistics.mean(values), 2),
            "median": round(statistics.median(values), 2),
            "min": round(min(values), 2),
            "max": round(max(values), 2),
            "range": round(max(values) - min(values), 2),
            "stdev": round(statistics.stdev(values), 2) if len(values) > 1 else 0
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ===========================================================================
# SMITH AGENT INTERFACE
# ===========================================================================

def run_numeric_tool(
    operation: str = "trend",
    values: List[float] = None,
    old_value: float = None,
    new_value: float = None,
    window: int = None
):
    """
    Dispatcher for numeric operations.
    
    Operations:
        - trend: Calculate trend from price history
        - percent_change: Calculate percentage change
        - statistics: Calculate descriptive statistics
    """
    # Input validation and type coercion
    def to_float_list(val):
        """Convert various input types to list of floats."""
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return [float(val)]
        if isinstance(val, str):
            # Try to convert single string to float
            try:
                return [float(val)]
            except ValueError:
                return None
        if isinstance(val, dict):
            # Handle finance_fetcher result objects
            if 'history' in val:
                # Extract close prices from history
                history = val['history']
                if isinstance(history, list):
                    result = []
                    for entry in history:
                        if isinstance(entry, dict) and 'close' in entry:
                            try:
                                result.append(float(entry['close']))
                            except (ValueError, TypeError):
                                continue
                    return result if result else None
            elif 'price' in val:
                # Extract single price
                try:
                    return [float(val['price'])]
                except (ValueError, TypeError):
                    return None
            elif 'value' in val:
                try:
                    return [float(val['value'])]
                except (ValueError, TypeError):
                    return None
        if isinstance(val, list):
            result = []
            for item in val:
                try:
                    if isinstance(item, (int, float)):
                        result.append(float(item))
                    elif isinstance(item, str):
                        result.append(float(item))
                    elif isinstance(item, dict):
                        # Handle dict items with numeric fields
                        if 'close' in item:
                            result.append(float(item['close']))
                        elif 'price' in item:
                            result.append(float(item['price']))
                        elif 'value' in item:
                            result.append(float(item['value']))
                        else:
                            continue
                    else:
                        continue
                except (ValueError, TypeError):
                    continue
            return result if result else None
        return None
    
    def to_float(val):
        """Convert single value to float."""
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            try:
                return float(val)
            except ValueError:
                return None
        if isinstance(val, dict):
            # Handle finance_fetcher price result
            if 'price' in val:
                try:
                    return float(val['price'])
                except (ValueError, TypeError):
                    return None
            # Handle history result - get first close price
            elif 'history' in val:
                history = val['history']
                if isinstance(history, list) and len(history) > 0:
                    first_entry = history[0]
                    if isinstance(first_entry, dict) and 'close' in first_entry:
                        try:
                            return float(first_entry['close'])
                        except (ValueError, TypeError):
                            return None
            # Generic value field
            elif 'value' in val:
                try:
                    return float(val['value'])
                except (ValueError, TypeError):
                    return None
        return None
    
    # Operation dispatch
    if operation == "trend":
        converted_values = to_float_list(values)
        if not converted_values:
            return {"status": "error", "error": "values required for trend calculation (must be numeric)"}
        return calculate_trend(converted_values, window)
    
    elif operation == "percent_change":
        converted_old = to_float(old_value)
        converted_new = to_float(new_value)
        if converted_old is None or converted_new is None:
            return {"status": "error", "error": "old_value and new_value required (must be numeric)"}
        return calculate_percent_change(converted_old, converted_new)
    
    elif operation == "statistics":
        converted_values = to_float_list(values)
        if not converted_values:
            return {"status": "error", "error": "values required for statistics (must be numeric)"}
        return calculate_statistics(converted_values)
    
    else:
        return {"status": "error", "error": f"Unknown operation: {operation}"}


numeric_computer = run_numeric_tool


METADATA = {
    "name": "numeric_computer",
    "description": "Perform deterministic calculations: trends, percent changes, statistics. Use this instead of asking LLM to compute numbers.",
    "function": "run_numeric_tool",
    "dangerous": False,
    "domain": "computation",
    "output_type": "numeric",
    "parameters": {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["trend", "percent_change", "statistics"],
                "description": "Type of calculation"
            },
            "values": {
                "type": "array",
                "items": {"type": "number"},
                "description": "List of numeric values for trend or statistics"
            },
            "old_value": {
                "type": "number",
                "description": "Old value for percent_change"
            },
            "new_value": {
                "type": "number",
                "description": "New value for percent_change"
            },
            "window": {
                "type": "integer",
                "description": "Window size for moving average (optional)"
            }
        },
        "required": ["operation"]
    }
}
