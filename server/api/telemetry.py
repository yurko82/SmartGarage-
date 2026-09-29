"""
FastAPI Telemetry API module with async ESP32 requests, exponential backoff,
Redis/In-Memory dual-layer caching, offline DB fallback, and Prometheus metrics.
"""
import os
import time
import json
import asyncio
import logging
from typing import Optional, Dict, Any, List
from pathlib import Path

import aiohttp
from fastapi import FastAPI, APIRouter, Query, Response, status
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

from server.config import config
from server.storage.telemetry_db import TelemetryDB

logger = logging.getLogger("TelemetryAPI")

# ------------------------------------------------------------------------------
# Prometheus Metrics Declarations
# ------------------------------------------------------------------------------
TELEMETRY_REQUESTS_TOTAL = Counter(
    "telemetry_requests_total",
    "Total count of telemetry history requests received",
    ["status", "source"]
)

TELEMETRY_REQUEST_DURATION_SECONDS = Histogram(
    "telemetry_request_duration_seconds",
    "Duration of telemetry requests in seconds",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

TELEMETRY_ESP32_UNAVAILABLE_TOTAL = Counter(
    "telemetry_esp32_unavailable_total",
    "Count of failed attempts reaching ESP32 requiring fallback"
)

# ------------------------------------------------------------------------------
# In-Memory Cache Fallback (30-second TTL)
# ------------------------------------------------------------------------------
class InMemoryCache:
    """Thread-safe and async-safe in-memory cache with TTL."""
    def __init__(self, default_ttl_sec: int = 30):
        self.default_ttl = default_ttl_sec
        self._store: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            if time.time() > entry["expires_at"]:
                del self._store[key]
                return None
            return entry["data"]

    async def set(self, key: str, value: Any, ttl_sec: Optional[int] = None):
        ttl = ttl_sec if ttl_sec is not None else self.default_ttl
        async with self._lock:
            self._store[key] = {
                "data": value,
                "expires_at": time.time() + ttl
            }

memory_cache = InMemoryCache(default_ttl_sec=30)

# ------------------------------------------------------------------------------
# Redis Client Connection (Optional / Graceful Degradation)
# ------------------------------------------------------------------------------
_redis_client = None

async def get_redis_client():
    global _redis_client
    if _redis_client is None:
        try:
            import redis.asyncio as aioredis
            redis_host = os.getenv("REDIS_HOST", "localhost")
            redis_port = int(os.getenv("REDIS_PORT", 6379))
            client = aioredis.Redis(host=redis_host, port=redis_port, db=0, socket_timeout=1.0)
            await client.ping()
            _redis_client = client
            logger.info("Connected to Redis cache at %s:%d", redis_host, redis_port)
        except Exception as e:
            logger.warning("Redis cache unavailable (%s). Falling back to in-memory cache.", e)
            _redis_client = False
    return _redis_client if _redis_client is not False else None


async def cache_get(key: str) -> Optional[Dict[str, Any]]:
    redis = await get_redis_client()
    if redis:
        try:
            val = await redis.get(key)
            if val:
                return json.loads(val)
        except Exception as e:
            logger.debug("Redis get error: %s", e)
    return await memory_cache.get(key)


async def cache_set(key: str, data: Dict[str, Any], ttl_sec: int = 30):
    redis = await get_redis_client()
    if redis:
        try:
            await redis.setex(key, ttl_sec, json.dumps(data))
        except Exception as e:
            logger.debug("Redis set error: %s", e)
    await memory_cache.set(key, data, ttl_sec=ttl_sec)


# ------------------------------------------------------------------------------
# Async ESP32 Client with Exponential Backoff
# ------------------------------------------------------------------------------
async def fetch_esp32_telemetry_history(floor: Optional[str], hours: float, limit: int) -> Optional[Dict[str, Any]]:
    """
    Query ESP32 with 5s timeout and exponential backoff retry (1s, 2s, 4s, 8s), max 3 attempts.
    """
    esp32_host = config.get("esp32.host", "192.168.100.114")
    esp32_port = config.get("esp32.port", 80)
    url = f"http://{esp32_host}:{esp32_port}/api/telemetry/history"
    params = {"hours": hours, "limit": limit}
    if floor:
        params["floor"] = floor

    timeout = aiohttp.ClientTimeout(total=5.0)
    backoff_delays = [1.0, 2.0, 4.0, 8.0]
    max_retries = 3

    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data
                    elif resp.status == 204:
                        return {"points": [], "stats": {}}
                    else:
                        logger.warning("ESP32 HTTP %d on attempt %d/%d", resp.status, attempt + 1, max_retries)
        except (aiohttp.ClientError, asyncio.TimeoutError) as ex:
            logger.warning("ESP32 request error on attempt %d/%d: %s", attempt + 1, max_retries, ex)

        if attempt < max_retries - 1:
            delay = backoff_delays[attempt]
            await asyncio.sleep(delay)

    TELEMETRY_ESP32_UNAVAILABLE_TOTAL.inc()
    return None


# ------------------------------------------------------------------------------
# FastAPI Router and Application
# ------------------------------------------------------------------------------
router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])
app = FastAPI(title="SmartGarage Telemetry API", version="2.0.0")

telemetry_db = TelemetryDB()


@router.get("/history")
@router.get("")
async def get_telemetry_history(
    floor: Optional[str] = Query(None, description="Floor key: basement, floor1, floor2"),
    hours: float = Query(24.0, ge=0.1, le=720.0, description="History window in hours"),
    limit: int = Query(500, ge=1, le=5000, description="Max points to return")
):
    """
    Optimized telemetry history endpoint:
    - 30-second Redis / In-memory caching
    - Async ESP32 queries with exponential backoff
    - Automatic SQLite fallback if ESP32 offline
    - 'data_age_seconds' calculation
    - HTTP 204 No Content if no data exists
    """
    start_time = time.time()
    cache_key = f"telemetry:history:{floor}:{hours}:{limit}"

    # 1. Check Cache
    cached = await cache_get(cache_key)
    if cached:
        TELEMETRY_REQUESTS_TOTAL.labels(status="200", source="cache").inc()
        TELEMETRY_REQUEST_DURATION_SECONDS.observe(time.time() - start_time)
        return JSONResponse(content=cached, status_code=status.HTTP_200_OK)

    # 2. Try fetching real-time data from ESP32
    esp32_result = await fetch_esp32_telemetry_history(floor=floor, hours=hours, limit=limit)

    source = "esp32"
    result_data = None

    if esp32_result and isinstance(esp32_result, dict):
        result_data = esp32_result
    else:
        # 3. Fallback to local SQLite DB
        source = "db_fallback"
        logger.info("Serving telemetry history from local SQLite database (floor=%s, hours=%.1f)", floor, hours)
        result_data = telemetry_db.get_history(floor=floor, hours=hours, limit=limit)

    # 4. Check for Empty Data -> Return 204 No Content
    points = result_data.get("points") or result_data.get("history") or []
    if not points:
        TELEMETRY_REQUESTS_TOTAL.labels(status="204", source=source).inc()
        TELEMETRY_REQUEST_DURATION_SECONDS.observe(time.time() - start_time)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # 5. Compute data_age_seconds
    now = time.time()
    latest_ts = None
    for p in points:
        ts = p.get("timestamp")
        if ts is not None and (latest_ts is None or ts > latest_ts):
            latest_ts = ts

    data_age_seconds = round(now - latest_ts, 1) if latest_ts else 0.0

    payload = {
        "success": True,
        "source": source,
        "floor": floor,
        "hours": hours,
        "data_age_seconds": max(0.0, data_age_seconds),
        "count": len(points),
        "points": points,
        "history": points, # Backwards compatibility with dashboard.js / app.js
        "stats": result_data.get("stats", {})
    }

    # 6. Save into Cache (30s TTL)
    await cache_set(cache_key, payload, ttl_sec=30)

    # 7. Record Prometheus Metrics
    duration = time.time() - start_time
    TELEMETRY_REQUESTS_TOTAL.labels(status="200", source=source).inc()
    TELEMETRY_REQUEST_DURATION_SECONDS.observe(duration)

    return JSONResponse(content=payload, status_code=status.HTTP_200_OK)


@app.get("/metrics")
async def prometheus_metrics():
    """Exposes Prometheus formatted telemetry metrics."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# Include router in FastAPI app
app.include_router(router)
