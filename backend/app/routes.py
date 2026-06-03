"""API routes: agents, threads, chat (SSE streaming), and message history."""
from __future__ import annotations

import asyncio
import json
from functools import lru_cache

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from .config import get_settings
from .mock_data import MockProvider
from .foundry_client import LiveProvider
from .models import (
    AgentInfo,
    ChatMessage,
    ChatRequest,
    CreateThreadResponse,
    HealthResponse,
)

router = APIRouter(prefix="/api")


@lru_cache
def get_provider():
    settings = get_settings()
    if settings.use_mock or not settings.live_ready:
        return MockProvider()
    return LiveProvider(settings)


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        use_mock=settings.use_mock or not settings.live_ready,
        live_ready=settings.live_ready,
        model_deployment=settings.model_deployment,
    )


@router.get("/agents", response_model=list[AgentInfo])
def list_agents() -> list[AgentInfo]:
    try:
        return get_provider().list_agents()
    except Exception as exc:  # pragma: no cover - surfaced to client
        raise HTTPException(status_code=502, detail=f"Failed to list agents: {exc}")


@router.post("/threads", response_model=CreateThreadResponse)
def create_thread() -> CreateThreadResponse:
    try:
        return CreateThreadResponse(thread_id=get_provider().create_thread())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to create thread: {exc}")


@router.get("/threads/{thread_id}/messages", response_model=list[ChatMessage])
def get_messages(thread_id: str) -> list[ChatMessage]:
    try:
        return get_provider().get_messages(thread_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to load messages: {exc}")


@router.post("/chat")
async def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    provider = get_provider()

    async def event_generator():
        thread_id = req.thread_id
        if not thread_id:
            thread_id = await asyncio.to_thread(provider.create_thread)
        # Tell the client which thread is in use (covers auto-created threads).
        yield {"event": "thread", "data": json.dumps({"thread_id": thread_id})}
        try:
            async for evt in provider.stream_chat(thread_id, req.message):
                yield {"event": evt["event"], "data": json.dumps(evt["data"])}
        except Exception as exc:  # pragma: no cover
            yield {"event": "error", "data": json.dumps({"message": str(exc)})}

    return EventSourceResponse(event_generator())
