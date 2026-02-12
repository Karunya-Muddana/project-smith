import sys
import os

# Add src to path
sys.path.insert(0, os.path.abspath("src"))

print("Testing imports...")

try:
    from smith.core.orchestrator import smith_orchestrator
    print("✅ smith.core.orchestrator imported")
except ImportError as e:
    print(f"❌ smith.core.orchestrator failed: {e}")

try:
    from smith.storage.mongodb import DBTools
    print("✅ smith.storage.mongodb imported")
except ImportError as e:
    print(f"❌ smith.storage.mongodb failed: {e}")

try:
    from smith.core.models import Trace
    print("✅ smith.core.models imported")
except ImportError as e:
    print(f"❌ smith.core.models failed: {e}")

try:
    from smith.tools.registry import registry
    print("✅ smith.tools.registry imported")
except ImportError as e:
    print(f"❌ smith.tools.registry failed: {e}")

try:
    import smith.planner
    print("✅ smith.planner imported")
except ImportError as e:
    print(f"❌ smith.planner failed: {e}")

print("\nDone.")
