import google.generativeai as genai
import os
from dotenv import load_dotenv

# Load API Key
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("❌ រកមិនឃើញ API Key ទេ។ សូមពិនិត្យ file .env ឡើងវិញ។")
else:
    genai.configure(api_key=api_key)
    print(f"🔑 កំពុងតេស្ត Key: ...{api_key[-4:]}")
    print("\n📋 បញ្ជី Model ដែលអ្នកប្រើបាន៖")
    print("---------------------------------")
    
    try:
        count = 0
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                print(f"✅ {m.name}")
                count += 1
        
        if count == 0:
            print("⚠️ មិនមាន Model ណាប្រើបានទេ។")
    except Exception as e:
        print(f"❌ មានបញ្ហា៖ {e}")