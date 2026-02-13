"""
SMITH REGISTRY POPULATOR
-------------------------
Script to auto-generate registry.json from tool modules.
Scans the tools directory and builds a JSON registry from METADATA in each module.
"""

import os
import sys
import json
import importlib.util
import logging


# Logging configuration
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("registry_populator")


# Configuration
TOOLBOX_DIR = os.path.join(os.path.dirname(__file__), "tools")
REGISTRY_FILE = os.path.join(TOOLBOX_DIR, "registry.json")


def extract_metadata(filepath):
    """
    Dynamically loads a Python file and returns the global METADATA dictionary
    if present. No import path assumptions required.
    """
    module_name = os.path.basename(filepath).replace(".py", "")
    spec = importlib.util.spec_from_file_location(module_name, filepath)

    if not spec or not spec.loader:
        return None

    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:
        logger.warning(f"Unable to load {filepath}: {exc}")
        return None

    meta = getattr(module, "METADATA", None)
    if isinstance(meta, dict):
        # If module name is missing, add it automatically
        if "module" not in meta:
            meta["module"] = f"smith.tools.{module_name}"
        return meta

    return None


def main():
    logger.info("Starting Smith Tool Registry generation")
    logger.info(f"Output file: {REGISTRY_FILE}")

    if not os.path.exists(TOOLBOX_DIR):
        logger.error(f"ToolBox directory not found: {TOOLBOX_DIR}")
        sys.exit(1)

    logger.info(f"Scanning ToolBox directory: {TOOLBOX_DIR}")

    tools = []

    for filename in sorted(os.listdir(TOOLBOX_DIR)):
        if not filename.endswith(".py") or filename.startswith("__"):
            continue

        path = os.path.join(TOOLBOX_DIR, filename)
        metadata = extract_metadata(path)

        if not metadata:
            logger.warning(f"Skipping {filename}: No metadata found")
            continue

        if "name" not in metadata:
            logger.warning(f"Skipping {filename}: Metadata missing 'name' field")
            continue

        tools.append(metadata)
        logger.info(f"Found: {metadata['name']} ({filename})")

    if not tools:
        logger.warning("No tools were found. Validate ToolBox contents.")
        sys.exit(1)

    # Build registry structure
    registry = {"version": "1.0", "auto_generated": True, "tools": tools}

    # Write to JSON file
    try:
        with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2, ensure_ascii=False)
        logger.info(f"✓ Successfully generated {REGISTRY_FILE}")
        logger.info(f"✓ Registered {len(tools)} tools")
    except Exception as exc:
        logger.error(f"Failed to write registry: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
