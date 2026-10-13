"""Health endpoints.

/health        liveness: the process is up. Never touches dependencies, so
               orchestrators do not restart the API when the database blips.
/health/ready  readiness: dependency connectivity (Postgres, Redis) with
               short timeouts. Returns 200 only when all dependencies pass;
               503 otherwise, with per dependency detail for debugging.
"""

import psycopg
import redis
from fastapi import APIRouter, Response, status

from app.config import APP_VERSION, get_settings

router = APIRouter(tags=["health"])

_TIMEOUT_SECONDS = 2


def _check_postgres(dsn: str) -> str:
    try:
        with psycopg.connect(dsn, connect_timeout=_TIMEOUT_SECONDS) as conn:
            conn.execute("SELECT 1")
        return "ok"
    except Exception as exc:  # noqa: BLE001 - report any failure as not ready
        return f"error: {type(exc).__name__}"


def _check_redis(url: str) -> str:
    try:
        client = redis.Redis.from_url(
            url,
            socket_connect_timeout=_TIMEOUT_SECONDS,
            socket_timeout=_TIMEOUT_SECONDS,
        )
        client.ping()
        return "ok"
    except Exception as exc:  # noqa: BLE001
        return f"error: {type(exc).__name__}"


@router.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "version": APP_VERSION,
        "environment": settings.environment,
    }


@router.get("/health/ready")
def ready(response: Response) -> dict[str, object]:
    settings = get_settings()
    deps = {
        "postgres": _check_postgres(settings.database_url),
        "redis": _check_redis(settings.redis_url),
    }
    all_ok = all(v == "ok" for v in deps.values())
    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if all_ok else "degraded", "dependencies": deps}
