"""FastAPI application entry point for the RFP Agent backend."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routes import router

settings = get_settings()

app = FastAPI(
    title="RFP Agent API",
    description="Reuses Microsoft Foundry agents for an RFP workflow.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
def root():
    return {"service": "rfp-agent-api", "docs": "/docs", "health": "/api/health"}
