"""
Financial Calculator Tool
Pure Python mathematical tool for calculating financial ratios.
No API keys or external services required.
"""

def calculate_cagr(start_value: float, end_value: float, years: float) -> dict:
    """Calculates Compound Annual Growth Rate."""
    if start_value <= 0 or years <= 0:
        return {"status": "error", "error": "Start value and years must be positive."}
    
    cagr = ((end_value / start_value) ** (1 / years)) - 1
    return {
        "status": "success",
        "result": {
            "type": "CAGR",
            "start_value": start_value,
            "end_value": end_value,
            "years": years,
            "cagr_decimal": round(cagr, 4),
            "cagr_percent": round(cagr * 100, 2)
        }
    }

def calculate_pe_premium(pe_a: float, pe_b: float) -> dict:
    """Calculates the premium/discount of PE A relative to PE B."""
    if pe_b <= 0:
        return {"status": "error", "error": "Base P/E must be positive."}
    
    premium_diff = pe_a - pe_b
    premium_percent = (premium_diff / pe_b) * 100
    
    return {
        "status": "success",
        "result": {
            "type": "PE_Premium",
            "pe_a": pe_a,
            "pe_b": pe_b,
            "absolute_difference": round(premium_diff, 2),
            "premium_percent": round(premium_percent, 2),
            "interpretation": f"Asset A is trading at a {abs(round(premium_percent, 2))}% {'premium' if premium_diff > 0 else 'discount'} to Asset B."
        }
    }

def calculate_dcf_baseline(free_cash_flow: float, growth_rate_percent: float, discount_rate_percent: float, terminal_multiple: float, years: int = 5) -> dict:
    """Calculates a baseline standard Discounted Cash Flow valuation."""
    if discount_rate_percent <= 0:
        return {"status": "error", "error": "Discount rate must be positive."}
        
    g = growth_rate_percent / 100.0
    r = discount_rate_percent / 100.0
    
    projected_fcfs = []
    current_fcf = free_cash_flow
    pv_sum = 0
    
    for year in range(1, years + 1):
        current_fcf *= (1 + g)
        pv = current_fcf / ((1 + r) ** year)
        projected_fcfs.append(round(current_fcf, 2))
        pv_sum += pv
        
    terminal_value = current_fcf * terminal_multiple
    pv_terminal = terminal_value / ((1 + r) ** years)
    
    intrinsic_value = pv_sum + pv_terminal
    
    return {
        "status": "success",
        "result": {
            "type": "DCF",
            "inputs": {
                "fcf_year_0": free_cash_flow,
                "growth_rate_percent": growth_rate_percent,
                "discount_rate_percent": discount_rate_percent,
                "terminal_multiple": terminal_multiple,
                "projection_years": years
            },
            "projected_fcfs": projected_fcfs,
            "present_value_of_fcfs": round(pv_sum, 2),
            "terminal_value": round(terminal_value, 2),
            "present_value_of_terminal": round(pv_terminal, 2),
            "intrinsic_value": round(intrinsic_value, 2)
        }
    }

def run_financial_calculator(operation: str, **kwargs) -> dict:
    """Main router for the financial calculator."""
    try:
        if operation == "cagr":
            return calculate_cagr(kwargs.get("start_value", 0), kwargs.get("end_value", 0), kwargs.get("years", 1))
        elif operation == "pe_premium":
            return calculate_pe_premium(kwargs.get("pe_a", 0), kwargs.get("pe_b", 1))
        elif operation == "dcf":
            return calculate_dcf_baseline(
                kwargs.get("free_cash_flow", 0), 
                kwargs.get("growth_rate_percent", 0), 
                kwargs.get("discount_rate_percent", 10), 
                kwargs.get("terminal_multiple", 10),
                kwargs.get("years", 5)
            )
        else:
            return {"status": "error", "error": f"Unknown operation: {operation}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}

METADATA = {
    "name": "financial_calculator",
    "description": "Calculate financial ratios (CAGR, PE Premium, DCF validation). Pure math, no API required.",
    "function": "run_financial_calculator",
    "dangerous": False,
    "domain": "computation",
    "output_type": "numeric",
    "parameters": {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["cagr", "pe_premium", "dcf"],
                "description": "The math operation to perform."
            },
            "start_value": {"type": "number", "description": "start value for CAGR"},
            "end_value": {"type": "number", "description": "end value for CAGR"},
            "years": {"type": "number", "description": "years for CAGR or DCF"},
            "pe_a": {"type": "number", "description": "PE of asset A for pe_premium"},
            "pe_b": {"type": "number", "description": "PE of base asset B for pe_premium"},
            "free_cash_flow": {"type": "number", "description": "starting FCF for DCF"},
            "growth_rate_percent": {"type": "number", "description": "annual growth percent for DCF"},
            "discount_rate_percent": {"type": "number", "description": "discount rate percent for DCF"},
            "terminal_multiple": {"type": "number", "description": "exit multiple for DCF"}
        },
        "required": ["operation"]
    }
}
