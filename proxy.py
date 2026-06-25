import os, json, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any
from fastapi import FastAPI, Request
from fastapi.responses import Response
import httpx
from dotenv import load_dotenv

load_dotenv()

TARGET = os.getenv("PROXY_TARGET", "https://generativelanguage.googleapis.com")
LOG = Path(__file__).parent / "logs" / "raw_traffic.json"
LOG.parent.mkdir(exist_ok=True)

PRICING = {
    "gemini-2.5-flash": {"prompt": 0.075, "completion": 0.3},
}

app = FastAPI()
client: httpx.AsyncClient = None

@app.on_event("startup")
async def start():
    global client
    client = httpx.AsyncClient(timeout=120.0)

@app.on_event("shutdown")
async def stop():
    await client.aclose()

def extract_token_counts(response_data: Any) -> Dict[str, int]:
    tokens = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    
    if isinstance(response_data, dict) and "usage" in response_data:
        usage = response_data["usage"]
        tokens["prompt_tokens"] = usage.get("prompt_tokens", 0)
        tokens["completion_tokens"] = usage.get("completion_tokens", 0)
        tokens["total_tokens"] = usage.get("total_tokens", 0)
    elif isinstance(response_data, str) and "data:" in response_data:
        for line in reversed(response_data.split("\n")):
            line = line.strip()
            if line.startswith("data:") and "[DONE]" not in line:
                try:
                    chunk = json.loads(line[5:].strip())
                    if "usage" in chunk and chunk["usage"]:
                        usage = chunk["usage"]
                        tokens["prompt_tokens"] = usage.get("prompt_tokens", 0)
                        tokens["completion_tokens"] = usage.get("completion_tokens", 0)
                        tokens["total_tokens"] = usage.get("total_tokens", 0)
                        break
                except: pass
    
    return tokens

def classify_error(status_code: int) -> Dict[str, Any]:
    error_info = {
        "error_type": "success",
        "error_category": None,
        "is_client_error": False,
        "is_server_error": False,
        "is_rate_limit": False
    }
    
    if 400 <= status_code < 500:
        error_info["error_type"] = "client_error"
        error_info["error_category"] = "4xx"
        error_info["is_client_error"] = True
        if status_code == 429:
            error_info["is_rate_limit"] = True
    elif 500 <= status_code < 600:
        error_info["error_type"] = "server_error"
        error_info["error_category"] = "5xx"
        error_info["is_server_error"] = True
    
    return error_info

def calculate_cost(tokens: Dict[str, int], model: str) -> Dict[str, float]:
    cost_info = {"prompt_cost": 0.0, "completion_cost": 0.0, "total_cost": 0.0}
    model_pricing = None
    for pricing_model in PRICING:
        if pricing_model in model.lower():
            model_pricing = PRICING[pricing_model]
            break
    
    if not model_pricing:
        return cost_info

    prompt_cost = (tokens["prompt_tokens"] / 1_000_000) * model_pricing["prompt"]
    completion_cost = (tokens["completion_tokens"] / 1_000_000) * model_pricing["completion"]
    
    cost_info["prompt_cost"] = round(prompt_cost, 6)
    cost_info["completion_cost"] = round(completion_cost, 6)
    cost_info["total_cost"] = round(prompt_cost + completion_cost, 6)
    
    return cost_info

@app.api_route("/{path:path}", methods=["GET","POST","PUT","DELETE","PATCH"])
async def proxy(request: Request, path: str):
    body = await request.body()
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")}
    resp = await client.request(request.method, f"{TARGET.rstrip('/')}/{path}", headers=headers, content=body)

    try: req_json = json.loads(body) if body else None
    except: req_json = body.decode(errors="replace") if body else None
    try: resp_json = json.loads(resp.content)
    except: resp_json = resp.text

    token_counts = extract_token_counts(resp_json)
    error_info = classify_error(resp.status_code)
    model = req_json.get("model", "unknown") if isinstance(req_json, dict) else "unknown"
    cost_info = calculate_cost(token_counts, model)    
    log_entry = {
        "meta": {
            "ts": datetime.now(timezone.utc).isoformat(),
            "id": str(uuid.uuid4())[:8],
        },
        "request": {
            "method": request.method,
            "path": f"/{path}",
            "body": req_json,
            "bytes": len(body),
        },
        "response": {
            "status": resp.status_code,
            "body": resp_json,
            "bytes": len(resp.content),
            "rate_limit": resp.headers.get("X-RateLimit-Limit"),
        },
        "metrics": {
            "tokens": token_counts,
            "error": error_info,
            "cost": cost_info,
        },
    }
    formatted = json.dumps(log_entry, indent=2, default=str)
    sections = formatted.split('",\n  "')
    spaced = '",\n\n  "'.join(sections)
    if LOG.exists() and LOG.stat().st_size > 0:
        with open(LOG, "r", encoding="utf-8") as f:
            existing = json.load(f)
    else:
        existing = []
    existing.append(log_entry)

    with open(LOG, "w", encoding="utf-8") as f:
        output = json.dumps(existing, indent=2, default=str)
        sections = output.split('",\n    "')
        spaced = '",\n\n    "'.join(sections)
        spaced = spaced.replace("    },\n    {", "    },\n\n    {")
        f.write(spaced)
    
    return Response(content=resp.content, status_code=resp.status_code,
        headers={k:v for k,v in resp.headers.items() if k.lower() not in ("transfer-encoding","content-encoding","content-length")})