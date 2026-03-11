from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import redis.asyncio as redis_async
import redis
import os
import json
import asyncio
from shared.schemas import AttackPayload
from typing import Optional

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── REDIS STATE LAYER ───
redis_host = os.getenv("REDIS_HOST", "localhost")
r = redis.Redis(host=redis_host, port=6379, decode_responses=True)

def get_state(key: str, default: dict):
    val = r.get(key)
    if val:
        return json.loads(val)
    r.set(key, json.dumps(default))
    return default

def set_state(key: str, value: dict):
    r.set(key, json.dumps(value))

# ─── SIMULATED DATABASE ───
users_db = {
    1: {"username": "alice", "is_admin": False, "role": "user"},
    2: {"username": "bob", "is_admin": False, "role": "user"},
    3: {"username": "charlie", "is_admin": True, "secret_key": "SECURE_37361F94", "role": "admin"}
}

# ─── VULNERABILITY 1: Information Disclosure ───
@app.get("/users/{user_id}")
def get_user_profile(user_id: int):
    if user_id not in users_db:
        raise HTTPException(status_code=404, detail="User not found")
    user = dict(users_db[user_id])
    user.pop("secret_key", None)
    return user

# ─── VULNERABILITY 2: Business Logic Flaw ───
@app.post("/buy")
def buy(payload: AttackPayload):
    wallet = get_state("app_wallet", {"balance": 100})
    if payload.quantity is None:
        raise HTTPException(status_code=400, detail="Quantity required")
    if payload.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")
    if payload.quantity > 100:
        raise HTTPException(status_code=400, detail="Quantity exceeds maximum")
    wallet["balance"] -= payload.quantity * 10
    if wallet["balance"] < 0:
        raise HTTPException(status_code=400, detail="Insufficient balance")
    set_state("app_wallet", wallet)
    return {"status": "success", "new_balance": wallet["balance"]}

# ─── VULNERABILITY 3: Broken Access Control ───
@app.post("/admin/withdraw")
def admin_withdraw(payload: AttackPayload, x_admin_token: Optional[str] = Header(None)):
    if x_admin_token != "SECURE_37361F94":
        raise HTTPException(status_code=403, detail="Unauthorized: Invalid Admin Token")
    wallet = get_state("app_wallet", {"balance": 100})
    vault = get_state("app_vault", {"admin_fund": 10000})
    amount = payload.quantity or 0
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Withdrawal amount must be positive")
    if amount > 1000:
        raise HTTPException(status_code=400, detail="Withdrawal exceeds single transaction limit")
    if vault["admin_fund"] < amount:
        raise HTTPException(status_code=400, detail="Insufficient Vault funds")
    vault["admin_fund"] -= amount
    wallet["balance"] += amount
    set_state("app_wallet", wallet)
    set_state("app_vault", vault)
    return {"status": "success", "new_balance": wallet["balance"], "vault_remaining": vault["admin_fund"]}

# ─── READ-ONLY ENDPOINTS ───
@app.get("/wallet")
def get_wallet():
    return get_state("app_wallet", {"balance": 100})

@app.get("/vault")
def get_vault():
    return get_state("app_vault", {"admin_fund": 10000})

@app.get("/debug")
def debug_info():
    return {"db_users": len(users_db), "redis_host": redis_host}

@app.get("/login")
def login():
    return {"status": "login_page"}

# ─── SSE STREAM FOR FRONTEND DASHBOARD ───
@app.get("/stream")
async def event_stream(request: Request):
    r_async = redis_async.Redis(host=redis_host, port=6379, decode_responses=True)
    pubsub = r_async.pubsub()
    await pubsub.subscribe("events", "commands")

    async def event_generator():
        try:
            async for message in pubsub.listen():
                if await request.is_disconnected():
                    break
                if message["type"] == "message":
                    yield f"data: {message['data']}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe()
            await r_async.aclose()

    response = StreamingResponse(event_generator(), media_type="text/event-stream")
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response

# ─── BLUE AGENT STATE ENDPOINT (polled by frontend) ───
@app.get("/api/blue_state")
def get_blue_state():
    patch_count = r.get("patch_count")
    patch_history = r.hgetall("PATCH_HISTORY") if r.exists("PATCH_HISTORY") else {}
    last_endpoint = list(patch_history.keys())[-1] if patch_history else None
    return {
        "patch_count": int(patch_count) if patch_count else 0,
        "last_endpoint": last_endpoint,
        "patch_history": patch_history
    }
