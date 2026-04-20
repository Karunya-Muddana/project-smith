"""
TOOL DIAGNOSTICS — Health Check System
--------------------------------------
Runs static and dynamic analysis on the ToolBox.
"""

from typing import List, Dict, Any


class ToolDiagnostics:
    def __init__(self):
        self.report = []

    def log(self, tool_name: str, status: str, message: str):
        self.report.append({"tool": tool_name, "status": status, "message": message})

    def run(self) -> List[Dict[str, Any]]:
        try:
            from smith.registry import get_tools_registry
            from smith.tool_loader import load_tool_function
        except ImportError as e:
            return [{"tool": "SYSTEM", "status": "CRITICAL", "message": f"Could not import smith modules: {e}"}]

        try:
            tools = get_tools_registry()
        except Exception as e:
            return [{"tool": "SYSTEM", "status": "CRITICAL", "message": f"Registry load failed: {e}"}]

        if not tools:
            return [{"tool": "SYSTEM", "status": "WARNING", "message": "No tools found in registry."}]

        for tool_meta in tools:
            name = tool_meta.get("name", "UNKNOWN")
            module_name = tool_meta.get("module", "")
            func_name = tool_meta.get("function", "")

            if not module_name or not func_name:
                self.log(name, "WARN", "Missing 'module' or 'function' in metadata.")
                continue

            try:
                load_tool_function(module_name, func_name)
                self.log(name, "OK", f"Ready ({module_name}.{func_name})")
            except (ImportError, AttributeError, TypeError) as e:
                self.log(name, "FAIL", str(e))

        return self.report


def run_diagnostics():
    diag = ToolDiagnostics()
    return diag.run()


tool_diagnostics = run_diagnostics

METADATA = {
    "name": "tool_diagnostics",
    "description": "Runs a health check on all installed tools. Detects broken imports, missing functions, or invalid metadata.",
    "function": "run_diagnostics",
    "dangerous": False,
    "domain": "system",
    "output_type": "diagnostic",
    "parameters": {"type": "object", "properties": {}, "required": []},
}


if __name__ == "__main__":
    import json
    print(json.dumps(run_diagnostics(), indent=2))
