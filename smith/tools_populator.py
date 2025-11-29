"""
SMITH DB POPULATOR (STANDALONE)
-------------------------------
Script to reset and repopulate the Tool Registry in MongoDB.
Scans the tools directory and inserts tool metadata found in each module.
"""

import os
import sys
import importlib.util
import logging

from pymongo import MongoClient


# Logging configuration
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("db_populator")


# Configuration
MONGO_URI = os.getenv("MONGO_URI", "mongodb://root:password@localhost:27017/?authSource=admin")
DB_NAME = "project_smith"
COLLECTION_NAME = "tools"
TOOLBOX_DIR = os.path.join(os.path.dirname(__file__), "tools")


def get_db_collection():
    """Establishes direct MongoDB connection and returns the tools collection."""
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
        client.server_info()
        return client[DB_NAME][COLLECTION_NAME]
    except Exception as exc:
        logger.error(f"Database connection failed: {exc}")
        sys.exit(1)


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
        meta.setdefault("module", module_name)
        return meta

    return None


def main():
    logger.info("Starting Smith Tool Registry reset")
    logger.info(f"Database: {DB_NAME}, Collection: {COLLECTION_NAME}")

    collection = get_db_collection()

    logger.info("Clearing existing registry")
    delete_result = collection.delete_many({})
    logger.info(f"Deleted {delete_result.deleted_count} records")

    if not os.path.exists(TOOLBOX_DIR):
        logger.error(f"ToolBox directory not found: {TOOLBOX_DIR}")
        sys.exit(1)

    logger.info(f"Scanning ToolBox directory: {TOOLBOX_DIR}")

    registered = 0

    for filename in sorted(os.listdir(TOOLBOX_DIR)):
        if not filename.endswith(".py") or filename.startswith("__"):
            continue

        path = os.path.join(TOOLBOX_DIR, filename)
        metadata = extract_metadata(path)

        if not metadata:
            logger.warning(f"Skipping {filename}: No metadata found")
            continue

        if "name" not in metadata or "function" not in metadata:
            logger.warning(f"Skipping {filename}: Metadata missing required fields")
            continue

        try:
            collection.insert_one(metadata)
            logger.info(f"Registered: {metadata['name']} ({filename})")
            registered += 1
        except Exception as exc:
            logger.error(f"Insert failed for {filename}: {exc}")

    if registered == 0:
        logger.warning("No tools were registered. Validate ToolBox contents.")
    else:
        logger.info(f"Completed. Tools registered: {registered}")


if __name__ == "__main__":
    main()
