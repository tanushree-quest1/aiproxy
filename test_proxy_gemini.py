import os
import time
from openai import OpenAI
from openai import APIError, RateLimitError, APIConnectionError
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    api_key=os.environ["GEMINI_API_KEY"],
    base_url="http://localhost:8000/v1beta/openai"  # proxy → Gemini's OpenAI-compatible endpoint
)

max_retries = 3
initial_delay = 1  # seconds