import os
import time
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

API_KEY = os.getenv("GOOGLE_API_KEY")
print(f"API Key present: {bool(API_KEY)}")

if API_KEY:
    genai.configure(api_key=API_KEY)

def test_model(model_name):
    print(f"\nTesting model: {model_name}")
    try:
        start = time.time()
        model = genai.GenerativeModel(model_name)
        response = model.generate_content("Say hello", request_options={"timeout": 10})
        duration = time.time() - start
        print(f"✅ Success ({duration:.2f}s): {response.text}")
    except Exception as e:
        print(f"❌ Failed: {e}")

test_model("gemini-2.5-flash")
test_model("gemini-1.5-flash")
