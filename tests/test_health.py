from fastapi.testclient import TestClient

from AZFlow.api import app


client = TestClient(app)

FASTAPI_BUILTIN_PATHS = {
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
}


def test_health_returns_200_and_healthy_body():
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_all_azflow_routes_are_version_prefixed():
    paths = [
        route.path
        for route in app.routes
        if isinstance(getattr(route, "path", None), str)
        and route.path not in FASTAPI_BUILTIN_PATHS
    ]

    assert paths, "expected at least one AZFlow API route"
    for path in paths:
        assert path.startswith("/api/v"), f"route without version prefix: {path}"
