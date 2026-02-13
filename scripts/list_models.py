import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")

if not api_key:
    with open("models.txt", "w") as f:
        f.write("No API Key found")
    exit(1)

genai.configure(api_key=api_key)

with open("models.txt", "w") as f:
    f.write("Listing available models:\n")
    try:
        for m in genai.list_models():
            if "generateContent" in m.supported_generation_methods:
                f.write(f"{m.name}\n")
    except Exception as e:
        f.write(f"Error listing models: {e}\n")
