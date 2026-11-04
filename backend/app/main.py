"""FastAPI entrypoint: Himalayan Sentinel disaster-response API."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    disaster_response,
    early_warning,
    health,
    reports,
    session,
    verification,
)
from app.core.config import settings

app = FastAPI(title="Himalayan Sentinel API", version="0.1.0")

# Browser frontends served from another origin (the Vite dev server by
# default) call this API with a custom session header, so CORS must
# allow it explicitly. Same-origin deployments are unaffected.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "x-session-id"],
)

app.include_router(health.router, prefix="/api")
# Bare /health alias: kept for load-balancer probes; pinned by tests.
app.include_router(health.router)
app.include_router(early_warning.router, prefix="/api")
app.include_router(disaster_response.router, prefix="/api")
app.include_router(verification.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(session.router, prefix="/api")


@app.get("/")
def root() -> dict:
    return {"service": "himalayan-sentinel", "status": "scaffold"}
