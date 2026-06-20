import json
from pathlib import Path

import config


def _write_jsonl(path: Path, entry: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def log_raw_traffic(entry: dict) -> None:
    _write_jsonl(config.RAW_TRAFFIC_LOG, entry)


def log_error(entry: dict) -> None:
    _write_jsonl(config.ERROR_LOG, entry)
