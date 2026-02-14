"""
Quick test for the web scraper tool
"""

from smith.tools.WEB_SCRAPER import run_web_scraper

print("Testing Web Scraper Tool...")
print("=" * 60)

# Test 1: Simple page
print("\n1. Testing with example.com:")
result = run_web_scraper("https://example.com")
print(f"Status: {result['status']}")
if result["status"] == "success":
    print(f"Title: {result['title']}")
    print(f"Content length: {result['length']} characters")
    print(f"Content preview: {result['content'][:200]}...")
else:
    print(f"Error: {result['error']}")

# Test 2: Without protocol
print("\n2. Testing without protocol (example.com):")
result2 = run_web_scraper("example.com")
print(f"Status: {result2['status']}")
if result2["status"] == "success":
    print(f"URL resolved to: {result2['url']}")
    print(f"Title: {result2['title']}")

# Test 3: Invalid URL
print("\n3. Testing with invalid URL:")
result3 = run_web_scraper("https://this-domain-definitely-does-not-exist-12345.com")
print(f"Status: {result3['status']}")
if result3["status"] == "error":
    print(f"Error (expected): {result3['error']}")

print("\n" + "=" * 60)
print("✅ Web scraper tests complete!")
