import logging

import psycopg
import redis
from fastapi import FastAPI

from app.admin.review_queue import router as review_queue_router
from app.api.chat import router as chat_router
from app.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="forge-api-gateway")
app.include_router(review_queue_router)
app.include_router(chat_router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/deep")
def health_deep():
    result = {"postgres": "unknown", "redis": "unknown"}

    try:
        with psycopg.connect(settings.postgres_dsn, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        result["postgres"] = "ok"
    except Exception as e:
        result["postgres"] = f"error: {e}"

    try:
        r = redis.from_url(settings.redis_url, socket_connect_timeout=3)
        r.ping()
        result["redis"] = "ok"
    except Exception as e:
        result["redis"] = f"error: {e}"

    return result
