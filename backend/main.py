"""
main.py — FastAPI application factory.

This file creates the app, registers routers, and configures middleware.
It is intentionally thin — no business logic lives here.

Run locally:
    cd backend
    uvicorn main:app --reload --port 8000

Then visit:
    http://localhost:8000/docs     ← interactive Swagger UI
    http://localhost:8000/redoc    ← ReDoc alternative
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from routers import games, players, teams, possessions


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.api_title,
        version=settings.api_version,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # -------------------------------------------------------------------------
    # CORS
    # -------------------------------------------------------------------------
    # Allow the React frontend (Phase 5) to call this API from localhost:3000.
    # Tighten origins in production — wildcard is for local dev only.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -------------------------------------------------------------------------
    # Routers
    # -------------------------------------------------------------------------
    app.include_router(games.router)
    app.include_router(players.router)
    app.include_router(teams.router)
    app.include_router(possessions.router)

    # -------------------------------------------------------------------------
    # Health check
    # -------------------------------------------------------------------------
    @app.get("/health", tags=["meta"])
    def health():
        """Returns 200 when the API is reachable. Used by Docker healthchecks."""
        return {"status": "ok", "version": settings.api_version}

    return app


app = create_app()
