from fastapi.testclient import TestClient

from app.config import APP_VERSION
from app.main import create_app

client = TestClient(create_app())


def test_health_returns_200_without_dependencies() -> None:
    """Liveness must not depend on Postgres or Redis being reachable."""
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == APP_VERSION


def test_ready_reports_dependency_detail() -> None:
    """Readiness returns per dependency status; 503 when any dependency fails.

    In CI without services this asserts the degraded path; with services up
    it asserts the healthy path. Both shapes are validated.
    """
    resp = client.get("/health/ready")
    body = resp.json()
    assert set(body["dependencies"].keys()) == {"postgres", "redis"}
    if resp.status_code == 200:
        assert body["status"] == "ok"
        assert all(v == "ok" for v in body["dependencies"].values())
    else:
        assert resp.status_code == 503
        assert body["status"] == "degraded"
