import sys
from smith.core.orchestrator import smith_orchestrator

# Simple query that should trigger LLM directly or Weather tool if registered
# We'll use a generic LLM query first to test end-to-end.
QUERY = "Explain quantum computing in 5 words."

print(f"Starting Live Test with Query: '{QUERY}'")
try:
    gen = smith_orchestrator(QUERY)
    for event in gen:
        e_type = event.get("type")
        if e_type == "status":
            print(f"[STATUS] {event.get('message')}")
        elif e_type == "step_start":
            print(f"[STEP] {event.get('tool')} -> {event.get('function')}")
        elif e_type == "step_complete":
            print(f"[DONE] {event.get('tool')} ({event.get('status')})")
        elif e_type == "final_answer":
            print(f"\n[SUCCESS] FINAL ANSWER:\n{event.get('payload')}")
        elif e_type == "error":
            print(f"[ERROR] {event.get('message')}")
            
except Exception as e:
    print(f"CRASH: {e}")
    import traceback
    traceback.print_exc()
