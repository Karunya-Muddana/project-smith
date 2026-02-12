"""
Tool Registry Loader
--------------------
Loads tool metadata from static JSON file instead of MongoDB.
"""

import json
import os
from typing import List, Dict, Any
from pathlib import Path

_REGISTRY_CACHE = None


def get_tools_registry() -> List[Dict[str, Any]]:
    """
    Load tool registry from JSON file.
    Returns list of tool metadata dictionaries.
    """
    global _REGISTRY_CACHE
    
    if _REGISTRY_CACHE is not None:
        return _REGISTRY_CACHE
    
    # Find registry.json relative to this file
    current_dir = Path(__file__).parent
    registry_path = current_dir / "tools" / "registry.json"
    
    if not registry_path.exists():
        raise FileNotFoundError(f"Tool registry not found at {registry_path}")
    
    with open(registry_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    _REGISTRY_CACHE = data.get("tools", [])
    return _REGISTRY_CACHE


def get_tool_by_name(tool_name: str) -> Dict[str, Any]:
    """Get metadata for a specific tool by name."""
    tools = get_tools_registry()
    for tool in tools:
        if tool["name"] == tool_name:
            return tool
    raise ValueError(f"Tool '{tool_name}' not found in registry")


def list_tool_names() -> List[str]:
    """Get list of all available tool names."""
    tools = get_tools_registry()
    return [t["name"] for t in tools]


def reset_cache():
    """Reset the registry cache. Useful for testing."""
    global _REGISTRY_CACHE
    _REGISTRY_CACHE = None
