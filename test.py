"""
Send a test request through the proxy to Gemini.
Start the proxy first: uvicorn proxy:app --port 8000
"""

import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    api_key=os.environ["GEMINI_API_KEY"],
    base_url="http://localhost:8000/v1beta/openai"  # proxy → Gemini's OpenAI-compatible endpoint
)

response = client.chat.completions.create(
    model="gemini-2.5-flash",
    messages=[{"role": "user", "content": "What is 2+2?"}]
)

print(response.choices[0].message.content)
print(f"\nCheck logs/raw_traffic.jsonl to see the raw request-response pair.")
