from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import make_sessionmaker
from app.ratelimit import RateLimiter
from app.routers import destinations, invites, plans, trips
from app.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Fábrica da aplicação: uvicorn app.main:create_app --factory."""
    settings = settings or get_settings()
    app = FastAPI(title="meridiano-api", version="0.1.0")
    app.state.settings = settings
    app.state.sessionmaker = make_sessionmaker(settings.database_url)
    app.state.parse_limiter = RateLimiter(settings.parse_rate_limit)
    app.state.plans_limiter = RateLimiter(settings.plans_rate_limit)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Content-Type", "X-Admin-Token", "X-Invite-Token"],
        expose_headers=["Retry-After"],
    )
    for module in (destinations, trips, invites, plans):
        app.include_router(module.router)

    @app.get("/health", include_in_schema=False)
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
