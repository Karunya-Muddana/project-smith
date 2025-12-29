import sys
import time
from smith.orchestrator import smith_orchestrator

QUERY = """
I need a market and tech brief.
1. Get the current stock price of TSLA (Tesla).
2. Search Google for 'Tesla robotaxi news 2024'.
3. Ask the LLM to write a short poem about electric cars.
4. Finally, synthesize all this into a 2-paragraph summary explaining if the news justifies the price.
"""

print(f"=== STARTING STRESS TEST ===")
print(f"Query Length: {len(QUERY)} chars")
print(f"Query: {QUERY.strip()}")
print("-" * 50)

start_time = time.time()
step_count = 0

try:
    gen = smith_orchestrator(QUERY)
    for event in gen:
        e_type = event.get("type")
        
        if e_type == "status":
            print(f"[STATUS] {event.get('message')}")
        elif e_type == "step_start":
            step_count += 1
            print(f"[STEP {step_count}] {event.get('tool')} -> {event.get('function')}")
        elif e_type == "step_complete":
            status = event.get("status")
            dur = event.get("duration")
            print(f"[DONE] {event.get('tool')} ({status}) [{dur}s]")
            if status == "error":
                print(f"    ERROR: {event.get('payload')}")
        elif e_type == "final_answer":
            print("-" * 50)
            print(f"[SUCCESS] FINAL ANSWER:\n{event.get('payload')}")
            print("-" * 50)
        elif e_type == "error":
            print(f"[CRITICAL ERROR] {event.get('message')}")

    total_time = round(time.time() - start_time, 2)
    print(f"=== TEST COMPLETE ===")
    print(f"Total Steps: {step_count}")
    print(f"Total Time: {total_time}s")

except Exception as e:
    print(f"CRASH: {e}")
    import traceback
    traceback.print_exc()
