import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

TARGET = os.getenv("PROXY_TARGET", "https://generativelanguage.googleapis.com")
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

RAW_TRAFFIC_LOG = LOG_DIR / "raw_traffic.jsonl"
ERROR_LOG = LOG_DIR / "errors.jsonl"
