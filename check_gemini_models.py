# check_gemini_models.py
import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()  # loads GEMINI_API_KEY from .env

# Put your key here or in .env
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    print("Error: GEMINI_API_KEY not found! Put it in .env or export it.")
    exit(1)

genai.configure(api_key=GEMINI_API_KEY)

print("Available Gemini models you can use right now (Nov 2025 – 2026):\n")
print(f"{'#':<3} {'Model name':<35} {'Display name':<30} {'Supports vision'}")
print("-" * 80)

for i, m in enumerate(genai.list_models(), 1):
    # Only show Gemini models (not embedding or older ones)
    if "gemini" not in m.name:
        continue

    vision = "Yes" if "vision" in m.supported_generation_methods else "No"
    print(f"{i:<3} {m.name:<35} {m.display_name:<30} {vision}")

print("\nRecommended for your News Bot (2026):")
print("   • gemini-3.0-flash      → fastest & cheapest (2026 default)")
print("   • gemini-2.0-flash      → still excellent, very cheap")
print("   • gemini-2.0-pro        → smarter, good for hard translations")
print("   • gemini-1.5-pro-002    → legacy but still works")