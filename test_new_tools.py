"""Quick test script for Wikipedia + URL Reader tools."""
import json
from src.smith.tools.WIKIPEDIA_LOOKUP import run_wikipedia_lookup
from src.smith.tools.URL_READER import run_url_reader

print("=" * 60)
print("TEST 1: Wikipedia Lookup")
print("=" * 60)
r1 = run_wikipedia_lookup("Free trade zone")
print(f"  Status:     {r1['status']}")
print(f"  Title:      {r1.get('title', 'N/A')}")
print(f"  Sections:   {len(r1.get('sections', []))}")
print(f"  Categories: {len(r1.get('categories', []))}")
print(f"  Summary:    {r1.get('summary', '')[:200]}...")

print()
print("=" * 60)
print("TEST 2: URL Reader")
print("=" * 60)
r2 = run_url_reader("https://en.wikipedia.org/wiki/Jebel_Ali_Free_Zone", max_length=5000)
print(f"  Status:     {r2['status']}")
print(f"  Title:      {r2.get('title', 'N/A')}")
print(f"  Length:     {r2.get('content_length', 0):,} chars")
print(f"  Sections:   {r2.get('sections', 0)}")

print()
print("DONE")
