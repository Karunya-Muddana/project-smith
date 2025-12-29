import sys
import os
from dotenv import load_dotenv

# Load environment
load_dotenv()

print("=== LIVE ENVIRONMENT CHECK ===")

# 1. Check API Key
api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
if api_key:
    print(f"[OK] GOOGLE_API_KEY found (length: {len(api_key)})")
else:
    print("[FAIL] GOOGLE_API_KEY or GEMINI_API_KEY not found in environment or .env")

# 2. Check MongoDB
try:
    from smith.tools.DB_TOOLS import DBTools
    db = DBTools()
    res = db.list_collections()
    if res.get("status") == "success":
        print("[OK] MongoDB Connected successfully.")
    else:
        print(f"[FAIL] MongoDB Connection Issue: {res.get('error')}")
except Exception as e:
    print(f"[FAIL] MongoDB Check crashed: {e}")

# 3. Check LLM Client
try:
    from smith.tools import LLM_CALLER
    if LLM_CALLER.client:
        print("[OK] LLM Client initialized.")
    else:
        print(f"[FAIL] LLM Client failed to init: {LLM_CALLER.init_error}")
except Exception as e:
    print(f"[FAIL] LLM Check crashed: {e}")
