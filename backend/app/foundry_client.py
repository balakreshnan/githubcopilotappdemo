"""Live provider: reuses existing Microsoft Foundry (Azure AI Foundry) agents.

This targets the current Foundry agent model exposed by ``azure-ai-projects`` (2.x),
where agents are versioned (ids look like ``name:version``) and are **invoked through
the OpenAI Responses API**, not the older thread/run model. We obtain an OpenAI client
bound to an existing agent via ``AIProjectClient.get_openai_client(agent_name=...)`` and
call ``responses.create(...)``.

Agents are **reused by name/id** — this module never creates or deletes agents.

The SDK is imported lazily so the app can run in mock mode without the azure packages
installed. Network calls are synchronous, so they are wrapped in ``asyncio.to_thread``
to avoid blocking the event loop.

A single Responses call returns the full ``output`` list: the assistant message (with
text + citation annotations) plus any tool / connected-agent call items. We parse those
items to surface each sub-agent's activity and the sources, then stream the final answer
to the UI in chunks for a live feel.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, AsyncGenerator, Optional

from .config import Settings
from .models import AgentInfo, AgentStep, ChatMessage, Source

# Output item types that are NOT sub-agent / tool activity worth surfacing.
# `mcp_list_tools` is just tool discovery; `message`/`reasoning` are the answer itself.
_NON_STEP_ITEM_TYPES = {"message", "reasoning", "mcp_list_tools"}


def _strip_text_prefix(s: str) -> str:
    """Strip stray ``text`` artifacts this Foundry preview prepends to answers.

    Two shapes have been observed:
      * a bare ``text`` immediately followed by the real answer, e.g. ``textAn RFI...``
        or ``text\\n\\nBased on...``
      * the whole answer wrapped as ``text[ <answer> ]``
    The bare prefix is stripped only when what follows is an uppercase letter,
    newline, or markdown marker, to avoid mangling answers that legitimately begin
    with the lowercase word "text".
    """
    s = s.strip()
    if s.startswith("text[") and s.endswith("]"):
        inner = s[len("text["):-1].strip()
        if inner:
            return inner
    if s.startswith("text") and len(s) > 4:
        nxt = s[4]
        if nxt.isupper() or nxt in "\n\r\t#*->•":
            return s[4:].lstrip()
    return s


def _decode_mcp_source(uri: str) -> Optional[tuple[str, str]]:
    """Turn an internal ``mcp://searchindex/<hash>_<base64-url>_pages_<n>`` citation into
    a friendly ``(title, url)``. Returns None if it isn't a decodable mcp source."""
    if not uri or "/searchindex/" not in uri:
        return None
    try:
        import base64
        import re
        from urllib.parse import unquote

        rest = uri.split("/searchindex/", 1)[1]
        _, _, after = rest.partition("_")  # drop the leading hash id
        page = None
        mp = re.search(r"_pages?_(\d+)$", after)
        if mp:
            page = mp.group(1)
            after = after[: mp.start()]
        b64 = after + "=" * (-len(after) % 4)
        try:
            decoded = base64.b64decode(b64).decode("utf-8", "ignore")
        except Exception:
            decoded = base64.urlsafe_b64decode(b64).decode("utf-8", "ignore")
        decoded = decoded.strip().strip("\r\n\t ")
        if not decoded.lower().startswith("http"):
            return None
        file_name = unquote(decoded.rsplit("/", 1)[-1]).replace("+", " ")
        title = f"{file_name} (p. {page})" if page else file_name
        return title, decoded
    except Exception:
        return None


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    """Read a field from an SDK object whether it's attr-, dict-, or mapping-style."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    val = getattr(obj, name, None)
    if val is not None:
        return val
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
        self._project = None
        self._openai_clients: dict[str, Any] = {}
        self._agent_meta_cache: Optional[list] = None
        # thread_id -> last response id, for multi-turn continuity via the Responses API.
        self._threads: dict[str, Optional[str]] = {}

    # ---- client lifecycle -------------------------------------------------
    def _project_client(self):
        if self._project is None:
            from azure.ai.projects import AIProjectClient
            from azure.identity import DefaultAzureCredential

            # When the Foundry resource is in a different tenant than the default
            # `az login` (e.g. you're a guest user), force the credential to that
            # tenant. DefaultAzureCredential reads AZURE_TENANT_ID from the env.
            if self.settings.azure_tenant_id:
                os.environ["AZURE_TENANT_ID"] = self.settings.azure_tenant_id

            # allow_preview is required to bind the OpenAI client to a named agent.
            self._project = AIProjectClient(
                endpoint=self.settings.project_endpoint,
                credential=DefaultAzureCredential(),
                allow_preview=True,
            )
        return self._project

    def _openai_for(self, agent_name: str):
        """An OpenAI client bound to a specific existing Foundry agent (cached)."""
        if agent_name not in self._openai_clients:
            self._openai_clients[agent_name] = self._project_client().get_openai_client(
                agent_name=agent_name
            )
        return self._openai_clients[agent_name]

    # ---- name/id resolution ----------------------------------------------
    def _agent_name_only(self, value: str) -> str:
        """Strip a trailing ``:version`` so ``rfpagent:6`` -> ``rfpagent``."""
        return value.split(":", 1)[0] if value else value

    def _main_agent_name(self) -> str:
        if self.settings.main_agent_name:
            return self._agent_name_only(self.settings.main_agent_name)
        if self.settings.main_agent_id:
            return self._agent_name_only(self.settings.main_agent_id)
        raise RuntimeError(
            "No main agent configured. Set MAIN_AGENT_NAME (recommended) or MAIN_AGENT_ID "
            "in backend/.env to the name of your RFP agent in the Foundry project."
        )

    def _all_agent_meta(self) -> list:
        """List agents in the project (cached, best-effort) for metadata lookups."""
        if self._agent_meta_cache is None:
            try:
                agents_ops = self._project_client().agents
                self._agent_meta_cache = list(agents_ops.list())
            except Exception:
                self._agent_meta_cache = []
        return self._agent_meta_cache

    def _describe(self, name: str) -> tuple[str, str]:
        """Return (id, description) for an agent name, best-effort."""
        target = self._agent_name_only(name).strip().lower()
        for a in self._all_agent_meta():
            a_name = (_attr(a, "name", "") or "").strip().lower()
            if a_name == target:
                return (
                    str(_attr(a, "id", name) or name),
                    str(_attr(a, "description", "") or ""),
                )
        return name, ""

    # ---- agent metadata ---------------------------------------------------
    def list_agents(self) -> list[AgentInfo]:
        infos: list[AgentInfo] = []

        main_name = self._main_agent_name()
        main_id, main_desc = self._describe(main_name)
        infos.append(
            AgentInfo(id=main_id, name=main_name, description=main_desc, role="main")
        )

        # Connected sub-agents are surfaced at runtime as tool calls, but any explicitly
        # configured ones are listed up-front so the directory isn't empty before a run.
        for cname in self.settings.connected_agent_name_list:
            cid, cdesc = self._describe(cname)
            infos.append(
                AgentInfo(
                    id=cid,
                    name=self._agent_name_only(cname),
                    description=cdesc,
                    role="connected",
                )
            )
        for cid in self.settings.connected_agent_id_list:
            infos.append(
                AgentInfo(
                    id=cid, name=self._agent_name_only(cid), description="", role="connected"
                )
            )
        return infos

    # ---- threads (client-side conversation handles) -----------------------
    def create_thread(self) -> str:
        thread_id = f"thread_{uuid.uuid4().hex}"
        self._threads[thread_id] = None
        return thread_id

    def get_messages(self, thread_id: str) -> list[ChatMessage]:
        # The Responses API keeps server-side state keyed by response id; the UI keeps
        # its own visible history, so there's nothing extra to reload here.
        return []

    # ---- chat / streaming -------------------------------------------------
    async def stream_chat(
        self, thread_id: str, message: str
    ) -> AsyncGenerator[dict, None]:
        agent_name = self._main_agent_name()
        previous_id = self._threads.get(thread_id)

        try:
            response = await asyncio.to_thread(
                self._create_response, agent_name, message, previous_id
            )
        except Exception as exc:  # surface a clear, actionable message to the UI
            yield {"event": "error", "data": {"message": self._friendly_error(exc)}}
            return

        # Remember the response id so the next turn continues the conversation.
        self._threads[thread_id] = _attr(response, "id")

        text, sources, steps = self._parse_response(response, agent_name)

        # Surface each sub-agent / tool call first, in order.
        for step in steps:
            yield {"event": "agent_step", "data": step.model_dump()}

        # Stream the final answer in chunks for a live typing feel.
        for chunk in _chunks(text, 24):
            yield {"event": "token", "data": {"text": chunk}}
            await asyncio.sleep(0.01)

        if sources:
            yield {"event": "sources", "data": [s.model_dump() for s in sources]}

        assistant = ChatMessage(
            role="assistant",
            content=text,
            agent_steps=steps,
            sources=sources,
        )
        yield {"event": "done", "data": {"message": assistant.model_dump()}}

    # ---- SDK call (sync, run via to_thread) -------------------------------
    def _create_response(self, agent_name: str, message: str, previous_id: Optional[str]):
        client = self._openai_for(agent_name)
        kwargs: dict[str, Any] = {"input": message}
        if previous_id:
            kwargs["previous_response_id"] = previous_id
        return client.responses.create(**kwargs)

    # ---- parsing ----------------------------------------------------------
    def _parse_response(
        self, response, main_agent_name: str
    ) -> tuple[str, list[Source], list[AgentStep]]:
        """Extract (final_text, sources, sub_agent_steps) from a Responses result."""
        steps: list[AgentStep] = []
        sources: list[Source] = []
        text_parts: list[str] = []

        for item in _attr(response, "output", []) or []:
            itype = (_attr(item, "type", "") or "").lower()

            if itype == "message":
                t, s = self._parse_message_item(item)
                if t:
                    text_parts.append(t)
                sources.extend(s)
                continue

            if itype in _NON_STEP_ITEM_TYPES:
                continue

            step = self._tool_item_to_step(item, itype)
            if step:
                steps.append(step)

        # Prefer the SDK's convenience join if we couldn't assemble message text.
        text = "\n".join(p for p in text_parts if p).strip()
        if not text:
            text = (_attr(response, "output_text", "") or "").strip()
        text = _strip_text_prefix(text)

        return text, _dedupe_sources(sources), steps

    def _parse_message_item(self, item) -> tuple[str, list[Source]]:
        text_parts: list[str] = []
        sources: list[Source] = []
        for block in _attr(item, "content", []) or []:
            btype = (_attr(block, "type", "") or "").lower()
            if btype in ("output_text", "text", ""):
                value = _attr(block, "text")
                if isinstance(value, str) and value:
                    text_parts.append(value)
                for ann in _attr(block, "annotations", []) or []:
                    src = self._annotation_to_source(ann)
                    if src:
                        sources.append(src)
            elif btype == "refusal":
                refusal = _attr(block, "refusal")
                if isinstance(refusal, str):
                    text_parts.append(refusal)
        return "\n".join(text_parts).strip(), sources

    def _tool_item_to_step(self, item, itype: str) -> Optional[AgentStep]:
        """Map a tool / connected-agent output item to an AgentStep."""
        name = (
            _attr(item, "name")
            or _attr(item, "server_label")
            or _attr(item, "agent_name")
            or itype.replace("_call", "").replace("_", " ").title()
            or "Tool"
        )

        input_text = self._stringify(
            _attr(item, "arguments")
            or _attr(item, "input")
            or _attr(item, "queries")
            or _attr(item, "query")
        )
        output_text = self._stringify(
            _attr(item, "output")
            or _attr(item, "response")
            or _attr(item, "results")
            or _attr(item, "result")
        )

        raw_status = (_attr(item, "status", "") or "").lower()
        if raw_status in ("failed", "incomplete", "error"):
            status = "failed"
        else:
            status = "completed"

        return AgentStep(
            id=str(_attr(item, "id", uuid.uuid4().hex)),
            agent_name=str(name),
            agent_id=_attr(item, "id"),
            status=status,  # type: ignore[arg-type]
            input=input_text or None,
            output=output_text or None,
        )

    def _annotation_to_source(self, ann) -> Optional[Source]:
        atype = (_attr(ann, "type", "") or "").lower()
        snippet = _attr(ann, "text") or _attr(ann, "quote") or ""

        if atype == "url_citation":
            url = _attr(ann, "url")
            decoded = _decode_mcp_source(url) if isinstance(url, str) else None
            if decoded:
                title, real_url = decoded
                return Source(
                    id=f"src_{uuid.uuid4().hex[:8]}",
                    title=title,
                    snippet=snippet,
                    url=real_url,
                    file_name=title,
                )
            return Source(
                id=f"src_{uuid.uuid4().hex[:8]}",
                title=_attr(ann, "title") or url or "Source",
                snippet=snippet,
                url=url,
            )
        if atype in ("file_citation", "file_path", "container_file_citation"):
            file_name = (
                _attr(ann, "filename")
                or _attr(ann, "file_name")
                or _attr(ann, "file_id")
                or "Document"
            )
            return Source(
                id=f"src_{uuid.uuid4().hex[:8]}",
                title=str(file_name),
                snippet=snippet,
                file_name=str(file_name),
            )
        return None

    # ---- helpers ----------------------------------------------------------
    @staticmethod
    def _stringify(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        try:
            import json

            return json.dumps(value, default=str, ensure_ascii=False)
        except Exception:
            return str(value)

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        msg = str(exc)
        low = msg.lower()
        if "403" in low or "permission" in low or "forbidden" in low:
            return (
                "Permission denied invoking the Foundry agent (HTTP 403). Your signed-in "
                "identity can list agents but is not allowed to run them. Grant it a role "
                "that includes 'Microsoft.MachineLearningServices/workspaces/agents/action' "
                "(e.g. 'Azure AI User' / 'Azure AI Project Manager') on the Foundry project, "
                "then retry. Original error: " + msg
            )
        if "404" in low or "not found" in low:
            return (
                "The configured agent was not found. Check MAIN_AGENT_NAME in backend/.env "
                "matches an agent in this Foundry project. Original error: " + msg
            )
        return f"Foundry agent call failed: {msg}"


def _dedupe_sources(sources: list[Source]) -> list[Source]:
    """Drop duplicate citations (same doc + url + snippet), preserving order."""
    seen: set[tuple] = set()
    out: list[Source] = []
    for s in sources:
        key = (s.title, s.url, s.file_name, s.snippet)
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _chunks(text: str, size: int):
    for i in range(0, len(text), size):
        yield text[i : i + size]
