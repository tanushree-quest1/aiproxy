import os, json, time, uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import Response
import httpx
from dotenv import load_dotenv

load_dotenv()

TARGET = os.getenv("PROXY_TARGET", "https://generativelanguage.googleapis.com")
LOG = Path(__file__).parent / "logs" / "raw_traffic.jsonl"
LOG.parent.mkdir(exist_ok=True)

app = FastAPI()
client: httpx.AsyncClient = None

@app.on_event("startup")
async def start():
    global client
    client = httpx.AsyncClient(timeout=120.0)
    print(f"Proxying to {TARGET} | Logging to {LOG}")

@app.on_event("shutdown")
async def stop():
    await client.aclose()

@app.api_route("/{path:path}", methods=["GET","POST","PUT","DELETE","PATCH"])
async def proxy(request: Request, path: str):
    body = await request.body()
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")}
    t0 = time.time()

    resp = await client.request(request.method, f"{TARGET.rstrip('/')}/{path}", headers=headers, content=body)

    # log raw pair
    try: req_json = json.loads(body) if body else None
    except: req_json = body.decode(errors="replace") if body else None
    try: resp_json = json.loads(resp.content)
    except: resp_json = resp.text

    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "id": str(uuid.uuid4())[:8],
            "method": request.method,
            "path": f"/{path}",
            "request": req_json,
            "response": resp_json,
            "status": resp.status_code,
            "ms": int((time.time() - t0) * 1000),
        }, default=str) + "\n")

    return Response(content=resp.content, status_code=resp.status_code,
        headers={k:v for k,v in resp.headers.items() if k.lower() not in ("transfer-encoding","content-encoding","content-length")})
