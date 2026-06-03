"""Live provider: reuses existing Microsoft Foundry (Azure AI Foundry) agents.

Uses the Azure AI Agents SDK with DefaultAzureCredential. Agents are **reused by ID** —
this module never creates or deletes agents.

The SDK is imported lazily so the app can run in mock mode without the azure packages
installed. The live path uses the synchronous SDK wrapped in ``asyncio.to_thread`` to
avoid blocking the event loop, and polls the run so connected sub-agent activity can be
streamed to the UI as it happens.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, AsyncGenerator, Optional

from .config import Settings
from .models import AgentInfo, AgentStep, ChatMessage, Source

_TERMINAL_STATES = {"completed", "failed", "cancelled", "expired"}
_FAILED_STATES = {"failed", "cancelled", "expired"}
_MAX_POLL_SECONDS = 180  # safety cap so an SSE request can't hang forever


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    """Read a field from an SDK object whether it's attr-, dict-, or mapping-style."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    val = getattr(obj, name, None)
    if val is not None:
        return val
    # Azure SDK models are mutable-mapping-like; fall back to item access.
    getter = getattr(obj, "get", None)
    if callable(getter):
        try:
            got = getter(name, default)
            if got is not None:
                return got
        except Exception:
            pass
    return default


class LiveProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = None
        self._agent_names: dict[str, str] = {}
        self._all_agents_cache: Optional[list] = None
        self._resolved_main_id: Optional[str] = None

    # ---- client lifecycle -------------------------------------------------
    def _get_client(self):
        if self._client is None:
            from azure.ai.projects import AIProjectClient
            from azure.identity import DefaultAzureCredential

            self._client = AIProjectClient(
                endpoint=self.settings.project_endpoint,
                credential=DefaultAzureCredential(),
            )
        return self._client

    def _agents(self):
        """Return the agents operations group across SDK shapes."""
        client = self._get_client()
        # azure-ai-projects exposes the agents ops as `.agents`
        return getattr(client, "agents", client)

    # ---- agent lookup by name --------------------------------------------
    def _all_agents(self, agents) -> list:
        """List every agent in the project (cached) for name-based resolution."""
        if self._all_agents_cache is None:
            try:
                if hasattr(agents, "list_agents"):
                    self._all_agents_cache = list(agents.list_agents())
                else:
                    self._all_agents_cache = list(agents.list())
            except Exception:
                self._all_agents_cache = []
        return self._all_agents_cache

    def _find_by_name(self, agents, name: str):
        target = name.strip().lower()
        for a in self._all_agents(agents):
            if (_attr(a, "name", "") or "").strip().lower() == target:
                return a
        return None

    def _resolve_agent(self, agents, by_id: str, by_name: str):
        """Resolve an agent to (id, name, description) from an id or a name."""
        if by_id:
            try:
                agent = agents.get_agent(by_id)
                return by_id, _attr(agent, "name", by_id) or by_id, _attr(agent, "description", "") or ""
            except Exception:
                return by_id, by_id, ""
        if by_name:
            agent = self._find_by_name(agents, by_name)
            if agent is not None:
                return (
                    _attr(agent, "id"),
                    _attr(agent, "name", by_name) or by_name,
                    _attr(agent, "description", "") or "",
                )
        return None

    def _main_agent_id(self, agents) -> str:
        """The orchestrator agent id, resolved from MAIN_AGENT_ID or MAIN_AGENT_NAME."""
        if self._resolved_main_id:
            return self._resolved_main_id
        resolved = self._resolve_agent(
            agents, self.settings.main_agent_id, self.settings.main_agent_name
        )
        if not resolved or not resolved[0]:
            raise RuntimeError(
                "Could not resolve the main agent. Set MAIN_AGENT_ID, or set "
                f"MAIN_AGENT_NAME to an agent that exists in this project "
                f"(looked for '{self.settings.main_agent_name}')."
            )
        self._resolved_main_id = resolved[0]
        return self._resolved_main_id

    # ---- agent metadata ---------------------------------------------------
    def list_agents(self) -> list[AgentInfo]:
        agents = self._agents()
        infos: list[AgentInfo] = []

        main = self._resolve_agent(
            agents, self.settings.main_agent_id, self.settings.main_agent_name
        )
        if main:
            self._agent_names[main[0]] = main[1]
            infos.append(AgentInfo(id=main[0], name=main[1], description=main[2], role="main"))

        connected_ids = self.settings.connected_agent_id_list
        connected_names = self.settings.connected_agent_name_list
        pairs = [(cid, "") for cid in connected_ids] + [("", cn) for cn in connected_names]
        for cid, cname in pairs:
            resolved = self._resolve_agent(agents, cid, cname)
            if not resolved or not resolved[0]:
                continue
            self._agent_names[resolved[0]] = resolved[1]
            infos.append(
                AgentInfo(
                    id=resolved[0], name=resolved[1], description=resolved[2], role="connected"
                )
            )
        return infos

    # ---- threads ----------------------------------------------------------
    def create_thread(self) -> str:
        agents = self._agents()
        thread = agents.threads.create() if hasattr(agents, "threads") else agents.create_thread()
        return _attr(thread, "id")

    def get_messages(self, thread_id: str) -> list[ChatMessage]:
        agents = self._agents()
        try:
            if hasattr(agents, "messages"):
                raw = list(agents.messages.list(thread_id=thread_id))
            else:
                raw = list(agents.list_messages(thread_id=thread_id))
        except Exception:
            return []
        messages: list[ChatMessage] = []
        for m in reversed(list(raw)):  # SDK returns newest-first
            role = _attr(m, "role", "assistant")
            text, sources = self._extract_text_and_sources(m)
            messages.append(
                ChatMessage(role=role, content=text, sources=sources)  # type: ignore[arg-type]
            )
        return messages

    # ---- chat / streaming -------------------------------------------------
    async def stream_chat(
        self, thread_id: str, message: str
    ) -> AsyncGenerator[dict, None]:
        agents = self._agents()

        await asyncio.to_thread(self._create_user_message, agents, thread_id, message)
        run = await asyncio.to_thread(self._create_run, agents, thread_id)
        run_id = _attr(run, "id")

        # call_id -> (emitted_status, has_output) for dedupe; collected -> latest AgentStep
        seen_steps: dict[str, tuple[str, bool]] = {}
        collected: dict[str, AgentStep] = {}
        deadline = time.monotonic() + _MAX_POLL_SECONDS
        status = ""

        # Poll the run, surfacing connected sub-agent steps as they appear.
        while True:
            run = await asyncio.to_thread(self._get_run, agents, thread_id, run_id)
            status = (_attr(run, "status", "") or "").lower()

            steps = await asyncio.to_thread(self._list_run_steps, agents, thread_id, run_id)
            for step in steps:
                for evt in self._steps_to_events(step, seen_steps, collected):
                    yield evt

            if status in _TERMINAL_STATES:
                break
            if status == "requires_action":
                yield {
                    "event": "error",
                    "data": {
                        "message": "The run requires client tool output, which this app "
                        "does not submit. Configure tools as connected agents or "
                        "server-side tools in Foundry."
                    },
                }
                return
            if time.monotonic() > deadline:
                yield {
                    "event": "error",
                    "data": {"message": "Timed out waiting for the agent run to finish."},
                }
                return
            await asyncio.sleep(1.0)

        # Final refresh: late-arriving connected-agent outputs after the terminal state.
        steps = await asyncio.to_thread(self._list_run_steps, agents, thread_id, run_id)
        for step in steps:
            for evt in self._steps_to_events(step, seen_steps, collected):
                yield evt

        if status != "completed":
            yield {
                "event": "error",
                "data": {"message": f"Run ended with status: {status}"},
            }
            return

        # Fetch the final assistant message, then stream its text and sources.
        final = await asyncio.to_thread(self._latest_assistant_message, agents, thread_id)
        text, sources = self._extract_text_and_sources(final)

        for chunk in _chunks(text, 24):
            yield {"event": "token", "data": {"text": chunk}}
            await asyncio.sleep(0.01)

        if sources:
            yield {"event": "sources", "data": [s.model_dump() for s in sources]}

        assistant = ChatMessage(
            role="assistant",
            content=text,
            agent_steps=list(collected.values()),
            sources=sources,
        )
        yield {"event": "done", "data": {"message": assistant.model_dump()}}

    # ---- SDK helpers (sync, run via to_thread) ----------------------------
    def _create_user_message(self, agents, thread_id: str, message: str) -> None:
        if hasattr(agents, "messages"):
            agents.messages.create(thread_id=thread_id, role="user", content=message)
        else:
            agents.create_message(thread_id=thread_id, role="user", content=message)

    def _create_run(self, agents, thread_id: str):
        agent_id = self._main_agent_id(agents)
        if hasattr(agents, "runs"):
            return agents.runs.create(thread_id=thread_id, agent_id=agent_id)
        return agents.create_run(thread_id=thread_id, agent_id=agent_id)

    def _get_run(self, agents, thread_id: str, run_id: str):
        if hasattr(agents, "runs"):
            return agents.runs.get(thread_id=thread_id, run_id=run_id)
        return agents.get_run(thread_id=thread_id, run_id=run_id)

    def _list_run_steps(self, agents, thread_id: str, run_id: str) -> list[Any]:
        # Request ascending order so the UI shows agents in the order they ran.
        try:
            if hasattr(agents, "run_steps"):
                try:
                    return list(
                        agents.run_steps.list(
                            thread_id=thread_id, run_id=run_id, order="asc"
                        )
                    )
                except TypeError:
                    return list(agents.run_steps.list(thread_id=thread_id, run_id=run_id))
            return list(agents.list_run_steps(thread_id=thread_id, run_id=run_id))
        except Exception:
            return []

    def _latest_assistant_message(self, agents, thread_id: str):
        if hasattr(agents, "messages"):
            raw = list(agents.messages.list(thread_id=thread_id))
        else:
            raw = list(agents.list_messages(thread_id=thread_id))
        for m in raw:  # newest-first
            if _attr(m, "role") == "assistant":
                return m
        return raw[0] if raw else None

    # ---- parsing ----------------------------------------------------------
    def _steps_to_events(
        self,
        step,
        seen: dict[str, tuple[str, bool]],
        collected: dict[str, "AgentStep"],
    ) -> list[dict]:
        """Convert a run step into agent_step events for connected sub-agents.

        Dedupes on (status, has_output) so a step first seen as completed-without-output
        is re-emitted once its output lands (Azure polling is eventually consistent).
        """
        events: list[dict] = []
        details = _attr(step, "step_details")
        if _attr(details, "type") != "tool_calls":
            return events

        tool_calls = _attr(details, "tool_calls", []) or []
        status = (_attr(step, "status", "") or "").lower()
        for call in tool_calls:
            call_id = _attr(call, "id", uuid.uuid4().hex)
            agent_name, agent_id, input_text, output_text = self._parse_connected_call(call)
            if agent_name is None:
                continue

            if status == "completed":
                emitted_status = "completed"
            elif status in _FAILED_STATES:
                emitted_status = "failed"
            else:
                emitted_status = "running"

            has_output = bool(output_text)
            key = (emitted_status, has_output)
            if seen.get(call_id) == key:
                continue
            seen[call_id] = key

            agent_step = AgentStep(
                id=call_id,
                agent_name=agent_name,
                agent_id=agent_id,
                status=emitted_status,  # type: ignore[arg-type]
                input=input_text,
                output=output_text if emitted_status != "running" else None,
            )
            collected[call_id] = agent_step
            events.append({"event": "agent_step", "data": agent_step.model_dump()})
        return events

    def _parse_connected_call(self, call) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        """Best-effort extraction of a connected-agent (or tool) call's I/O."""
        call_type = _attr(call, "type", "")

        # Connected agent tool call.
        connected = _attr(call, "connected_agent")
        if connected is not None:
            name = _attr(connected, "name") or _attr(connected, "agent_name") or "Connected agent"
            return (
                name,
                _attr(connected, "agent_id") or _attr(connected, "id"),
                _attr(connected, "input") or _attr(connected, "arguments"),
                _attr(connected, "output") or _attr(connected, "response"),
            )

        # Generic function/tool call — surface as a tool step.
        if call_type == "function":
            fn = _attr(call, "function")
            name = _attr(fn, "name", "function")
            return (
                f"Tool: {name}",
                None,
                _attr(fn, "arguments"),
                _attr(fn, "output"),
            )

        if call_type in {"file_search", "azure_ai_search", "bing_grounding"}:
            return (f"Tool: {call_type}", None, None, None)

        return (None, None, None, None)

    def _extract_text_and_sources(self, message) -> tuple[str, list[Source]]:
        if message is None:
            return "", []
        text_parts: list[str] = []
        sources: list[Source] = []

        content = _attr(message, "content", []) or []
        for block in content:
            text_obj = _attr(block, "text")
            if text_obj is None and isinstance(block, str):
                text_parts.append(block)
                continue
            value = _attr(text_obj, "value")
            if value:
                text_parts.append(value)
            for ann in _attr(text_obj, "annotations", []) or []:
                src = self._annotation_to_source(ann)
                if src:
                    sources.append(src)

        # Fallback for SDKs exposing a flat text property.
        if not text_parts:
            flat = _attr(message, "text")
            if isinstance(flat, str):
                text_parts.append(flat)

        return "\n".join(text_parts).strip(), sources

    def _annotation_to_source(self, ann) -> Optional[Source]:
        file_cit = _attr(ann, "file_citation")
        url_cit = _attr(ann, "url_citation")
        quote = _attr(ann, "text") or ""
        if file_cit is not None:
            return Source(
                id=f"src_{uuid.uuid4().hex[:8]}",
                title=_attr(file_cit, "file_name") or _attr(file_cit, "file_id") or "Document",
                snippet=_attr(file_cit, "quote") or quote,
                file_name=_attr(file_cit, "file_name"),
            )
        if url_cit is not None:
            return Source(
                id=f"src_{uuid.uuid4().hex[:8]}",
                title=_attr(url_cit, "title") or _attr(url_cit, "url") or "Source",
                snippet=quote,
                url=_attr(url_cit, "url"),
            )
        return None


def _chunks(text: str, size: int):
    for i in range(0, len(text), size):
        yield text[i : i + size]
