"""
TOOL DIAGNOSTICS — Health Check System
--------------------------------------
Runs static and dynamic analysis on the ToolBox.
"""

import sys
import os
from typing import List, Dict, Any


# ===========================================================================
# DIAGNOSTIC LOGIC
# ===========================================================================


class ToolDiagnostics:
    def __init__(self):
        self.report = []

    def log(self, tool_name: str, status: str, message: str):
        self.report.append({"tool": tool_name, "status": status, "message": message})

    def run(self) -> List[Dict[str, Any]]:
        # --- LAZY IMPORT (Prevents Circular Import Errors) ---
        try:
            # We assume tool_loader is in the parent/root directory
            sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from tool_loader import (
                register_all_tools,
                load_tool_module,
                load_tool_function,
            )
        except ImportError as e:
            return [
                {
                    "tool": "SYSTEM",
                    "status": "CRITICAL",
                    "message": f"Could not import tool_loader: {e}",
                }
            ]

        # 1. Scan Files
        try:
            tools = register_all_tools()
        except Exception as e:
            return [
                {
                    "tool": "SYSTEM",
                    "status": "CRITICAL",
                    "message": f"Loader Failed: {str(e)}",
                }
            ]

        if not tools:
            return [
                {"tool": "SYSTEM", "status": "WARNING", "message": "No tools found."}
            ]

        # 2. Validate
        for tool_meta in tools:
            name = tool_meta.get("name", "UNKNOWN")
            module_name = tool_meta.get("module")
            target_func = tool_meta.get("function")

            # Check A: Import
            module = load_tool_module(module_name)
            if isinstance(module, dict) and "error" in module:
                self.log(name, "FAIL", f"Import Error: {module['error']}")
                continue

            # Check B: Function
            func_obj = load_tool_function(module_name, target_func)
            if isinstance(func_obj, dict) and "error" in func_obj:
                self.log(name, "FAIL", f"Function '{target_func}' missing.")
                continue

            self.log(name, "OK", f"Ready ({module_name})")

        return self.report


def run_diagnostics():
    diag = ToolDiagnostics()
    return diag.run()


# ===========================================================================
# METADATA (SMS v1.0)
# ===========================================================================

tool_diagnostics = run_diagnostics

METADATA = {
    "name": "tool_diagnostics",
    "description": "Runs a health check on all installed tools. Detects broken imports, missing functions, or invalid metadata.",
    "function": "run_diagnostics",
    "dangerous": False,
    "parameters": {"type": "object", "properties": {}, "required": []},
}


if __name__ == "__main__":
    print(run_diagnostics())
