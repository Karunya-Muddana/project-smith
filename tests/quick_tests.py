"""
Quick Stress Test Script - Interactive
---------------------------------------
Paste these queries into Smith CLI one at a time.
"""

tests = {
    "Test 1 - Authority Check": "What is the current AAPL stock price and what's the percentage change from yesterday?",
    
    "Test 2 - Capability Gap": "Extract text from this image file",
    
    "Test 3 - Numeric Computation": "Get MSFT stock history for last 5 days and calculate the trend direction",
    
    "Test 4 - News Clustering": "Search for AI news and group them by topic",
    
    "Test 5 - Weather + News": "Get weather in New York and search for related weather news",
    
    "Test 6 - Simple Query": "What tools are available in Smith?"
}

print("=" * 80)
print("SMITH STRESS TESTS - Quick Execution Guide")
print("=" * 80)
print("\nCopy and paste each query into Smith CLI:\n")

for i, (name, query) in enumerate(tests.items(), 1):
    print(f"\n{i}. {name}")
    print(f"   Query: {query}")
    print("   Then run: /inspect")
    print("-" * 80)

print("\n\nAfter each test, check:")
print("  • /inspect - View DAG flowchart")
print("  • /trace - Check quality scores")
print("  • Logs - Look for violations/warnings")
print("\n" + "=" * 80)
