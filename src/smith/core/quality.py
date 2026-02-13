"""
Quality Scoring & Observability
--------------------------------
Semantic success grading and execution quality metrics.
Extends validator.py with execution-level scoring.
"""

from typing import Dict, Any, List


def grade_execution_quality(trace: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Grade overall execution quality based on trace.

    Returns:
        {
            "overall_quality": "excellent" | "good" | "degraded" | "poor",
            "score": 0-100,
            "issues": List[str],
            "metrics": {...}
        }
    """
    if not trace:
        return {
            "overall_quality": "unknown",
            "score": 0,
            "issues": ["Empty trace"],
            "metrics": {},
        }

    total_steps = len(trace)
    successful = sum(1 for t in trace if t.get("status") == "success")
    errors = sum(1 for t in trace if t.get("status") == "error")
    violations = sum(1 for t in trace if t.get("violations"))
    degraded = sum(1 for t in trace if t.get("quality") == "degraded")

    # Calculate base score
    success_rate = (successful / total_steps) * 100 if total_steps > 0 else 0

    # Penalties
    violation_penalty = violations * 15  # Heavy penalty for authority violations
    degraded_penalty = degraded * 10
    error_penalty = errors * 20

    score = max(0, success_rate - violation_penalty - degraded_penalty - error_penalty)

    # Issues list
    issues = []
    if violations > 0:
        issues.append(f"{violations} authority violation(s) detected")
    if degraded > 0:
        issues.append(f"{degraded} degraded execution(s)")
    if errors > 0:
        issues.append(f"{errors} error(s)")

    # Overall grade
    if score >= 90 and not violations:
        quality = "excellent"
    elif score >= 75:
        quality = "good"
    elif score >= 50:
        quality = "degraded"
    else:
        quality = "poor"

    return {
        "overall_quality": quality,
        "score": round(score, 1),
        "issues": issues,
        "metrics": {
            "total_steps": total_steps,
            "successful": successful,
            "errors": errors,
            "violations": violations,
            "degraded": degraded,
            "success_rate": round(success_rate, 1),
        },
    }


def generate_quality_warning(trace_entry: Dict[str, Any]) -> str:
    """Generate human-readable warning for degraded executions."""
    quality = trace_entry.get("quality", "unknown")
    violations = trace_entry.get("violations", [])
    tool = trace_entry.get("tool", "unknown")

    if quality == "violated":
        return f"⚠️  {tool}: Multiple authority violations - {', '.join(violations)}"
    elif quality == "degraded":
        return f"⚠️  {tool}: Degraded quality - {violations[0] if violations else 'unknown issue'}"
    elif quality == "correct":
        return ""
    else:
        return f"⚠️  {tool}: Unknown quality status"
