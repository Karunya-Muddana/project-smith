"""
TOOL LOADER — Package-Aware Edition
-----------------------------------
Resolves and imports tool modules from the internal smith.tools package.
- Case-insensitive filename matching
- Works regardless of CWD (uses __file__ path)
"""

import importlib
import os
import sys
from types import ModuleType

# ---------------------------------------------------------------------------
# Locate tools directory & package name
# ---------------------------------------------------------------------------

# tools live in smith/tools
TOOLS_DIR = os.path.join(os.path.dirname(__file__), "tools")
TOOLS_PKG = "smith.tools"

if not os.path.isdir(TOOLS_DIR):
    raise RuntimeError(
        f"Tools folder not found at {TOOLS_DIR}. "
        "Expected structure: project-root/smith/tools/*.py"
    )

# Ensure project root is on sys.path so 'smith' is importable
project_root = os.path.dirname(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.append(project_root)


# ---------------------------------------------------------------------------
# Helper: fuzzy match tool module filenames
# ---------------------------------------------------------------------------

def resolve_module_filename(requested_name: str):
    """
    Match DB module name (e.g. 'FINANCE', 'finance.py') with actual file:
    FILE_MANAGER.py, file_Manager.py, file_manager.py etc.
    """
    requested_lower = requested_name.replace(".py", "").strip().lower()

    for file in os.listdir(TOOLS_DIR):
        if not file.endswith(".py"):
            continue
        filename_no_ext = file[:-3]

        if filename_no_ext.lower() == requested_lower:
            return filename_no_ext  # canonical module name without extension

    return None  # not found


# ---------------------------------------------------------------------------
# Module loader
# ---------------------------------------------------------------------------

def load_tool_module(module_name: str):
    """
    Import a tool module using fuzzy filename resolution.

    Accepts:
      - 'FINANCE'
      - 'FINANCE.py'
      - 'finance'
    Returns:
      - imported module object
      - or {"error": "..."} dict on failure
    """
    clean = module_name.replace(".py", "").strip()
    resolved = resolve_module_filename(clean)

    if resolved is None:
        return {"error": f"Cannot find module file for '{module_name}' in {TOOLS_PKG}/"}

    try:
        import_path = f"{TOOLS_PKG}.{resolved}"
        module = importlib.import_module(import_path)

        if not isinstance(module, ModuleType):
            return {"error": f"Module '{resolved}' is not a valid Python module"}

        return module

    except Exception as exc:
        return {"error": f"Failed to import '{resolved}' from package '{TOOLS_PKG}': {exc}"}


# ---------------------------------------------------------------------------
# Function loader
# ---------------------------------------------------------------------------

def load_tool_function(module_name: str, func_name: str):
    """
    Load a callable function from a resolved module.

    Returns either:
      - callable
      - {"error": "..."} dict
    """
    module = load_tool_module(module_name)

    if isinstance(module, dict):  # error propagated
        return module

    try:
        func = getattr(module, func_name, None)
        if func is None:
            return {"error": f"Function '{func_name}' not found in module '{module_name}'"}

        if not callable(func):
            return {"error": f"'{func_name}' in '{module_name}' is not callable"}

        return func

    except Exception as exc:
        return {"error": f"Error accessing '{func_name}' in '{module_name}': {exc}"}


# ---------------------------------------------------------------------------
# Tool Loader Self-Test
# ---------------------------------------------------------------------------

def test_tool_system():
    print("=== TOOL LOADER SELF-TEST ===")
    print(f"Tools Directory: {TOOLS_DIR}")
    print(f"Tools Package  : {TOOLS_PKG}\n")

    for file in os.listdir(TOOLS_DIR):
        if not file.endswith(".py") or file.startswith("_"):
            continue

        name = file[:-3]
        print(f"Testing module: {name}")

        m = load_tool_module(name)
        if isinstance(m, dict):
            print("  ❌ Import error:", m["error"])
            continue

        print("  ✔ Module imported")

        funcs = [
            f for f in dir(m)
            if callable(getattr(m, f))
            and not f.startswith("__")
        ]
        print("  Functions:", ", ".join(funcs) if funcs else "(none)")
        print()

    print("=== END SELF-TEST ===")


if __name__ == "__main__":
    test_tool_system()
