"""
Utility functions for Smith
"""

import threading
import traceback
from typing import Any, Callable, Dict

from smith.config import config


def execute_with_timeout(
    fn: Callable, args: Dict[str, Any], timeout: float
) -> Dict[str, Any]:
    """
    Run a tool function in a thread with a hard timeout.
    Normalize output to {status, result|error}.
    """
    res: Dict[str, Any] = {"ok": False, "value": None, "error": None}

    def target():
        try:
            res["value"] = fn(**args)
            res["ok"] = True
        except Exception as exc:
            res["error"] = str(exc)
            if config.debug_mode:
                traceback.print_exc()

    th = threading.Thread(target=target, daemon=True)
    th.start()
    th.join(timeout)

    if th.is_alive():
        return {"status": "error", "error": f"Execution timed out ({timeout}s)"}

    if not res["ok"]:
        return {"status": "error", "error": res["error"]}

    out = res["value"]
    if isinstance(out, dict):
        if "status" in out:
            return out
        return {"status": "success", "result": out}
    return {"status": "success", "result": out}
