"""Mock provider: canned multi-agent RFP responses so the UI runs without Azure.

Implements the same async interface as the live Foundry provider so routes can swap
between them based on the USE_MOCK setting.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import AsyncGenerator

from .models import AgentInfo, AgentStep, ChatMessage, Source

# Simulated specialized RFP agents (an orchestrator fanning out to sub-agents).
MOCK_AGENTS: list[AgentInfo] = [
    AgentInfo(
        id="agent_orchestrator",
        name="RFP Orchestrator",
        description="Coordinates specialized agents to assemble a complete RFP response.",
        role="main",
    ),
    AgentInfo(
        id="agent_requirements",
        name="Requirements Analyst",
        description="Extracts and structures the requirements from the RFP.",
        role="connected",
    ),
    AgentInfo(
        id="agent_compliance",
        name="Compliance Reviewer",
        description="Checks mandatory criteria, certifications, and constraints.",
        role="connected",
    ),
    AgentInfo(
        id="agent_technical",
        name="Technical Solution Architect",
        description="Designs the proposed solution and approach.",
        role="connected",
    ),
    AgentInfo(
        id="agent_pricing",
        name="Pricing Estimator",
        description="Builds a cost model and pricing summary.",
        role="connected",
    ),
    AgentInfo(
        id="agent_writer",
        name="Proposal Writer",
        description="Synthesizes everything into a polished proposal answer.",
        role="connected",
    ),
]


def _sub_agents() -> list[AgentInfo]:
    return [a for a in MOCK_AGENTS if a.role == "connected"]


def _step_payload(agent: AgentInfo, message: str) -> AgentStep:
    canned = {
        "agent_requirements": (
            f"Identified 6 core requirements from the request: "
            f"\"{message[:60]}...\". Top priorities: scalability, security, and SLA.",
        ),
        "agent_compliance": (
            "Verified ISO 27001 and SOC 2 Type II coverage. One gap flagged: "
            "data residency must be confirmed for the EU region.",
        ),
        "agent_technical": (
            "Proposed a containerized, multi-region architecture on managed services "
            "with autoscaling and a 99.95% availability target.",
        ),
        "agent_pricing": (
            "Estimated a 12-month engagement: $480K implementation + $18K/mo run cost. "
            "Includes a 10% contingency buffer.",
        ),
        "agent_writer": (
            "Assembled the executive summary, solution overview, compliance matrix, "
            "and pricing table into a client-ready proposal.",
        ),
    }
    output = canned.get(agent.id, ("Completed analysis.",))[0]
    return AgentStep(
        id=f"step_{uuid.uuid4().hex[:8]}",
        agent_name=agent.name,
        agent_id=agent.id,
        status="completed",
        input=message,
        output=output,
    )


def _mock_sources() -> list[Source]:
    return [
        Source(
            id="src_1",
            title="RFP-2024-Infrastructure.pdf — Section 3: Requirements",
            snippet="The solution must support 10,000 concurrent users with 99.9% uptime "
            "and full audit logging.",
            file_name="RFP-2024-Infrastructure.pdf",
            agent="Requirements Analyst",
        ),
        Source(
            id="src_2",
            title="Company-Compliance-Handbook.pdf — Certifications",
            snippet="Acme Corp maintains ISO 27001:2022 and SOC 2 Type II certifications, "
            "audited annually.",
            file_name="Company-Compliance-Handbook.pdf",
            agent="Compliance Reviewer",
        ),
        Source(
            id="src_3",
            title="Reference Architecture — Multi-Region",
            snippet="Recommended pattern: active-active across two regions with managed "
            "container orchestration and global load balancing.",
            url="https://learn.microsoft.com/azure/architecture/",
            agent="Technical Solution Architect",
        ),
        Source(
            id="src_4",
            title="Pricing-Model-FY24.xlsx — Engagement Tiers",
            snippet="Enterprise tier blended rate $185/hr; managed run services billed "
            "monthly with volume discounts above 500 hours.",
            file_name="Pricing-Model-FY24.xlsx",
            agent="Pricing Estimator",
        ),
    ]


def _final_answer(message: str) -> str:
    return (
        "## RFP Response Summary\n\n"
        f"Based on your request — *\"{message.strip()}\"* — here is the consolidated "
        "proposal assembled by the specialized agents:\n\n"
        "### Executive Summary\n"
        "We propose a secure, multi-region, containerized platform designed to meet the "
        "RFP's scalability and availability requirements while satisfying all mandatory "
        "compliance criteria.\n\n"
        "### Requirements Coverage\n"
        "- **Scale:** 10,000 concurrent users supported with autoscaling.\n"
        "- **Availability:** 99.95% SLA (exceeds the 99.9% requirement).\n"
        "- **Security & Audit:** Full audit logging and encryption in transit and at rest.\n\n"
        "### Compliance\n"
        "| Requirement | Status |\n"
        "| --- | --- |\n"
        "| ISO 27001 | ✅ Covered |\n"
        "| SOC 2 Type II | ✅ Covered |\n"
        "| EU Data Residency | ⚠️ Needs confirmation |\n\n"
        "### Proposed Architecture\n"
        "Active-active deployment across two regions with managed container "
        "orchestration, global load balancing, and a 99.95% availability target.\n\n"
        "### Pricing\n"
        "Estimated **$480K** implementation over 12 months plus **$18K/month** run cost, "
        "including a 10% contingency buffer.\n\n"
        "_See the **Sources** panel for the underlying documents and the **Agent Activity** "
        "panel for each specialist's contribution._"
    )


class MockProvider:
    """In-memory mock implementation of the agent provider interface."""

    def __init__(self) -> None:
        self._threads: dict[str, list[ChatMessage]] = {}

    def list_agents(self) -> list[AgentInfo]:
        return MOCK_AGENTS

    def create_thread(self) -> str:
        thread_id = f"thread_{uuid.uuid4().hex[:12]}"
        self._threads[thread_id] = []
        return thread_id

    async def stream_chat(
        self, thread_id: str, message: str
    ) -> AsyncGenerator[dict, None]:
        history = self._threads.setdefault(thread_id, [])
        history.append(ChatMessage(role="user", content=message))

        steps: list[AgentStep] = []

        # Orchestrator kicks off.
        orchestrator = AgentStep(
            id=f"step_{uuid.uuid4().hex[:8]}",
            agent_name="RFP Orchestrator",
            agent_id="agent_orchestrator",
            status="running",
            input=message,
        )
        yield {"event": "agent_step", "data": orchestrator.model_dump()}
        await asyncio.sleep(0.4)

        # Each sub-agent runs in sequence.
        for agent in _sub_agents():
            running = AgentStep(
                id=f"step_{uuid.uuid4().hex[:8]}",
                agent_name=agent.name,
                agent_id=agent.id,
                status="running",
                input=message,
            )
            yield {"event": "agent_step", "data": running.model_dump()}
            await asyncio.sleep(0.6)

            done = _step_payload(agent, message)
            done.id = running.id  # keep same step id so the UI updates in place
            steps.append(done)
            yield {"event": "agent_step", "data": done.model_dump()}

        # Orchestrator completes.
        orchestrator.status = "completed"
        orchestrator.output = "Synthesized all specialist outputs into the final proposal."
        yield {"event": "agent_step", "data": orchestrator.model_dump()}
        await asyncio.sleep(0.3)

        # Stream the final answer token-by-token.
        answer = _final_answer(message)
        full = ""
        for chunk in _chunks(answer, 24):
            full += chunk
            yield {"event": "token", "data": {"text": chunk}}
            await asyncio.sleep(0.03)

        sources = _mock_sources()
        yield {"event": "sources", "data": [s.model_dump() for s in sources]}

        assistant = ChatMessage(
            role="assistant",
            content=full,
            agent_steps=[orchestrator] + steps,
            sources=sources,
        )
        history.append(assistant)
        yield {"event": "done", "data": {"message": assistant.model_dump()}}


def _chunks(text: str, size: int):
    for i in range(0, len(text), size):
        yield text[i : i + size]
