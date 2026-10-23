from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings

# CORS: só as origens de CORS_ORIGINS (o front local e o de produção) recebem
# permissão do navegador para chamar a API.

LOCAL = "http://localhost:5173"
PRODUCTION = "https://planner.example.com"


def preflight(client: TestClient, origin: str):
    return client.options(
        "/trips",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-admin-token",
        },
    )


def test_cors_allows_only_configured_origins(migrated):
    settings = Settings(_env_file=None, database_url=migrated, cors_origins=f" {LOCAL} , {PRODUCTION}/ ")
    assert settings.cors_origin_list == [LOCAL, PRODUCTION]
    with TestClient(create_app(settings)) as client:
        for origin in (LOCAL, PRODUCTION):
            response = preflight(client, origin)
            assert response.status_code == 200
            assert response.headers["access-control-allow-origin"] == origin
            assert "x-admin-token" in response.headers["access-control-allow-headers"].lower()

        assert preflight(client, "https://outro.example.com").status_code == 400
        response = client.get("/destinations", headers={"Origin": PRODUCTION})
        assert response.headers["access-control-allow-origin"] == PRODUCTION
        assert response.headers["access-control-expose-headers"] == "Retry-After"
        response = client.get("/destinations", headers={"Origin": "https://outro.example.com"})
        assert "access-control-allow-origin" not in response.headers


def test_cors_origins_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", f"{LOCAL},{PRODUCTION}")
    assert Settings(_env_file=None).cors_origin_list == [LOCAL, PRODUCTION]
