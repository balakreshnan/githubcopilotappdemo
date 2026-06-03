"""Shared Pydantic models for API requests, responses, and SSE event payloads."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class AgentInfo(BaseModel):
    id: str
    name: str
    description: str = ""
    role: Literal["main", "connected"] = "connected"


class Source(BaseModel):
    id: str
    title: str
    snippet: str = ""
    url: Optional[str] = None
    file_name: Optional[str] = None
    agent: Optional[str] = None  # which sub-agent surfaced this source


class AgentStep(BaseModel):
    id: str
    agent_name: str
    agent_id: Optional[str] = None
    status: Literal["running", "completed", "failed"] = "running"
    input: Optional[str] = None
    output: Optional[str] = None


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = ""
    agent_steps: list[AgentStep] = []
    sources: list[Source] = []


class CreateThreadResponse(BaseModel):
    thread_id: str


class ChatRequest(BaseModel):
    thread_id: Optional[str] = None
    message: str


class HealthResponse(BaseModel):
    status: str
    use_mock: bool
    live_ready: bool
    model_deployment: str = ""
