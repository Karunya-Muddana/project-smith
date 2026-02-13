"""
DB TOOLS — MongoDB Connection
-----------------------------
Single source of truth for Mongo access.
Uses .env for credentials and works with Docker auth + root user.
"""

import os
import logging
import pymongo
from dotenv import load_dotenv

# load env from project root, not just current folder
ROOT_ENV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"
)
load_dotenv(ROOT_ENV)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] db_tools: %(message)s"
)
logger = logging.getLogger("db_tools")

MONGO_USER = os.getenv("MONGO_USER", "root")
MONGO_PASS = os.getenv("MONGO_PASS", "password")
MONGO_HOST = os.getenv("MONGO_HOST", "localhost")
MONGO_PORT = os.getenv("MONGO_PORT", "27017")
DB_NAME = os.getenv("MONGO_DB", "project_smith")

# correct auth source for root user
MONGO_URI = f"mongodb://{MONGO_USER}:{MONGO_PASS}@{MONGO_HOST}:{MONGO_PORT}/{DB_NAME}?authSource=admin"


class DBTools:
    def __init__(self):
        self.client = None
        self.db = None
        try:
            logger.info(f"Connecting ➜ {MONGO_URI}")
            self.client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
            self.client.admin.command("ping")  # verify authentication
            self.db = self.client[DB_NAME]
            logger.info(f"🟢 Mongo connected | Database = '{DB_NAME}'")
        except Exception as e:
            logger.error(f"❌ Database connection failed: {e}")
            self.client = None
            self.db = None

    def _ensure_conn(self):
        # This method seems to be missing a condition to check if self.db is None
        # Assuming the intent is to return an error if not connected, otherwise None
        if not self.db:
            return {"status": "error", "error": "DB not connected"}
        return None

    def list_collections(self):
        if e := self._ensure_conn():
            return e
        try:
            return {"status": "success", "collections": self.db.list_collection_names()}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def create_collection(self, collection_name: str):
        if e := self._ensure_conn():
            return e
        try:
            self.db.create_collection(collection_name)
            return {
                "status": "success",
                "message": f"Collection '{collection_name}' created.",
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def insert_one(self, collection_name: str, document: dict):
        if e := self._ensure_conn():
            return e
        try:
            res = self.db[collection_name].insert_one(document)
            return {"status": "success", "inserted_id": str(res.inserted_id)}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def read_many(self, collection_name: str, query: dict = None, limit: int = 10):
        if e := self._ensure_conn():
            return e
        try:
            query = query or {}
            cursor = self.db[collection_name].find(query).limit(limit)
            docs = []
            for d in cursor:
                d["_id"] = str(d["_id"])
                docs.append(d)
            return {"status": "success", "count": len(docs), "data": docs}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def read_one(self, collection_name: str, query: dict):
        if e := self._ensure_conn():
            return e
        try:
            d = self.db[collection_name].find_one(query)
            if d:
                d["_id"] = str(d["_id"])
            return {"status": "success", "data": d}
        except Exception as e:
            return {"status": "error", "error": str(e)}


# ENTRY POINT FOR ORCHESTRATOR
def run_db_tool(
    operation: str, collection: str = "", data: dict = None, query: dict = None
):
    db = DBTools()
    data = data or {}
    query = query or {}

    if operation == "list_collections":
        return db.list_collections()
    if not collection:
        return {"status": "error", "error": "Collection name required."}
    if operation == "create_collection":
        return db.create_collection(collection)
    if operation == "insert":
        return db.insert_one(collection, data)
    if operation == "read":
        return db.read_many(collection, query)
    return {"status": "error", "error": f"Unknown operation: {operation}"}


database_tool = run_db_tool
