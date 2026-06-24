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
LOG = Path(__file__).parent / "logs" / "raw_traffic.jsonl"
LOG.parent.mkdir(exist_ok=True)

PRICING = {
    "gpt-4": {"prompt": 30.0, "completion": 60.0},
    "gpt-4-turbo": {"prompt": 10.0, "completion": 30.0},
    "gpt-3.5-turbo": {"prompt": 0.5, "completion": 1.5},
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

def extract_user_id(headers: Dict[str, str]) -> Optional[str]:
    user_id_headers = [
        "x-user-id", "user-id", "user_id", 
        "x-user", "user", "authorization",
        "x-api-key", "api-key"
    ]
    
    for header in user_id_headers:
        if header in headers:
            user_id = headers[header]
            # Clean up authorization headers
            if header in ["authorization", "x-api-key", "api-key"]:
                if user_id.startswith("Bearer "):
                    user_id = user_id[7:].split(".")[0][:8]  # First 8 chars of JWT
                else:
                    user_id = user_id[:8]
            return user_id
    
    return None

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
    user_id = extract_user_id(dict(request.headers))
    
    log_entry = {
        "meta": {
            "ts": datetime.now(timezone.utc).isoformat(),
            "id": str(uuid.uuid4())[:8],
            "user_id": user_id,
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
    
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, default=str) + "\n")
    
    return Response(content=resp.content, status_code=resp.status_code,
        headers={k:v for k,v in resp.headers.items() if k.lower() not in ("transfer-encoding","content-encoding","content-length")})