"""
Tool Loader
-----------
Dynamically resolves and imports tool modules from the `smith.tools` package.
Supports case-insensitive "fuzzy" matching for user convenience.
"""

import importlib
import logging
import pkgutil
from typing import Callable, Optional

import smith.tools

logger = logging.getLogger("smith.tool_loader")


def _get_tools_package_path() -> str:
    """Retrieve the filesystem path of the smith.tools package."""
    if not smith.tools.__path__:
        raise RuntimeError("smith.tools is not a package (no __path__).")
    return list(smith.tools.__path__)[0]


def resolve_module_name(requested_name: str) -> Optional[str]:
    """
    Find the canonical module name in smith.tools case-insensitively.

    Args:
        requested_name: 'finance', 'FINANCE.py'

    Returns:
        Canonical module name (e.g., 'FINANCE') or None.
    """
    clean_req = requested_name.replace(".py", "").strip().lower()

    # Iterate over all modules in the smith.tools package
    for _, name, _ in pkgutil.iter_modules(smith.tools.__path__):
        if name.lower() == clean_req:
            return name

    return None


def load_tool_function(module_name: str, func_name: str) -> Callable:
    """
    Load a specific function from a tool module.

    Args:
        module_name: Name of the module (fuzzy matched) or full path like 'smith.tools.MODULE'
        func_name: Name of the function to import

    Returns:
        The callable function object.

    Raises:
        ImportError: If module cannot be loaded.
        AttributeError: If function is missing.
        TypeError: If target is not callable.
    """
    # Strip 'smith.tools.' prefix if present
    if module_name.startswith("smith.tools."):
        module_name = module_name.replace("smith.tools.", "")
    
    canonical_name = resolve_module_name(module_name)

    if not canonical_name:
        raise ImportError(f"Tool module '{module_name}' not found in smith.tools.")

    full_module_path = f"smith.tools.{canonical_name}"

    try:
        module = importlib.import_module(full_module_path)
    except Exception as e:
        raise ImportError(f"Failed to import {full_module_path}: {e}") from e

    func = getattr(module, func_name, None)
    if func is None:
        raise AttributeError(
            f"Module '{full_module_path}' has no function '{func_name}'."
        )

    if not callable(func):
        raise TypeError(f"'{func_name}' in {full_module_path} is not callable.")

    return func


# Self-test if run directly
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("=== TOOL LOADER DIAGNOSTICS ===")
    try:
        path = _get_tools_package_path()
        print(f"Package Path: {path}")

        print("\nAvailable Modules:")
        for _, name, _ in pkgutil.iter_modules([path]):
            print(f" - {name}")

    except Exception as e:
        print(f"Error: {e}")
