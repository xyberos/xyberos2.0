"""The triage workflow: classify, ground, draft — and stop before anything is sent.

This is the composition the path is about. Each step does one thing and writes one row; the edges
say what may follow; and the graph **ends at a draft**. There is no step that sends, no tool that
sends, and no path from a model's output to a customer's inbox: sending is a separate call that a
person with the right role has to make, which is the boundary the whole design protects.

Each capability is also a method, so the same code serves a single call from a route and a step in
the graph. A composition that only exists inside a workflow is a composition nobody can test in
isolation.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any

from support_desk.knowledge import KnowledgeBase
from support_desk.security import Principal
from support_desk.service import CATEGORIES, CONFIDENCES, TicketService
from support_desk.usage import UsageLog
from xyberos import Inject, Retry, StepContext, Workflow, seconds
from xyberos.ai import AIFacade, ChatRequest, Message, Usage

CLASSIFICATION_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": list(CATEGORIES)},
        "confidence": {"type": "string", "enum": list(CONFIDENCES)},
    },
    "required": ["category", "confidence"],
    "additionalProperties": False,
}

CLASSIFY_PROMPT = "Classify a ticket: the category that fits best, and how confident you are."

DRAFT_PROMPT = (
    "Draft a short reply to the customer. Use the quoted policy if one is given, and promise "
    "nothing the policy does not say. Write only the reply."
)

#: Below this confidence the desk asks a person instead of drafting: a draft costs money and
#: attention, and a wrong category is worse than a slow one.
LOW_CONFIDENCE = "low"


class Triage:
    """Runs the desk's triage, and owns none of the transitions it performs.

    The transitions belong to the service, which keeps this module about *composing* a model call
    with an application rule rather than about deciding who may do what.
    """

    def __init__(
        self,
        tickets: Annotated[TicketService, Inject()],
        knowledge: Annotated[KnowledgeBase, Inject()],
        assistant: Annotated[AIFacade, Inject()],
        usage: Annotated[UsageLog, Inject()],
    ) -> None:
        self._tickets = tickets
        self._knowledge = knowledge
        self._assistant = assistant
        self._usage = usage
        self._workflow = self._build()

    @property
    def workflow(self) -> Workflow:
        """Return the graph, which is a value: it can be rendered and inspected without running."""
        return self._workflow

    async def classify(self, principal: Principal, ticket_id: int) -> dict[str, object]:
        """Ask the model what a ticket is, then let the service record the answer."""
        ticket = await self._tickets.get_ticket(principal, ticket_id)
        response = await self._assistant.chat(
            ChatRequest(
                messages=(
                    Message.system(CLASSIFY_PROMPT),
                    Message.user(f"{ticket['subject']}\n\n{ticket['body']}"),
                ),
                response_schema=CLASSIFICATION_SCHEMA,
            )
        )
        payload = response.structured
        if not isinstance(payload, Mapping):
            raise AssertionError("a response schema that validated produced no payload")
        classified = await self._tickets.classify(
            principal,
            ticket_id,
            category=payload["category"],
            confidence=payload["confidence"],
        )
        await self._record(principal, ticket_id, "classify", response.model, response.usage)
        return classified

    async def ground(self, principal: Principal, ticket_id: int) -> str:
        """Return the passage that answers a ticket best, or an empty string when none matches."""
        ticket = await self._tickets.get_ticket(principal, ticket_id)
        hits = await self._knowledge.search(f"{ticket['subject']}\n{ticket['body']}", limit=1)
        return str(hits[0]["text"]) if hits else ""

    async def draft(
        self, principal: Principal, ticket_id: int, *, grounding: str = ""
    ) -> dict[str, object]:
        """Write a draft and store it, which sends nothing and waits for a person."""
        ticket = await self._tickets.get_ticket(principal, ticket_id)
        response = await self._assistant.chat(
            ChatRequest(
                messages=(
                    Message.system(DRAFT_PROMPT),
                    Message.user(
                        f"{ticket['subject']}\n\n{ticket['body']}\n\n"
                        f"Policy: {grounding or 'none found'}"
                    ),
                )
            )
        )
        suggestion = await self._tickets.attach_suggestion(
            principal, ticket_id, body=response.message.content, model=response.model
        )
        await self._record(principal, ticket_id, "draft", response.model, response.usage)
        return suggestion

    async def run(self, principal: Principal, ticket_id: int) -> dict[str, object]:
        """Run the workflow for one ticket, and return where it finished."""
        result: Any = await self._workflow.run(
            input={"principal": principal, "ticket": ticket_id}, timeout=seconds(30)
        )
        state = await self._tickets.state_of(principal, ticket_id)
        return {
            "ticket": ticket_id,
            "state": state,
            "steps": {step: outcome.status.value for step, outcome in result.steps.items()},
        }

    def _build(self) -> Workflow:
        """Define the graph once, at construction, so a malformed workflow fails at startup."""
        workflow = (
            Workflow("triage", version="1", input_type=dict)
            .step("classify", self._classify_step, retry=Retry(max_attempts=2), timeout=seconds(5))
            .step("ground", self._ground_step, timeout=seconds(5))
            .step("draft", self._draft_step, retry=Retry(max_attempts=2), timeout=seconds(10))
            .step("flag", self._flag_step)
            .edge("classify", "ground", when=lambda value: value["confidence"] != LOW_CONFIDENCE)
            .edge("classify", "flag", when=lambda value: value["confidence"] == LOW_CONFIDENCE)
            .edge("ground", "draft")
        )
        workflow.validate()
        return workflow

    async def _classify_step(self, value: dict[str, Any], context: StepContext) -> dict[str, Any]:
        """The classification capability as a step: the model answers, the service records it."""
        principal, ticket_id = _call(value)
        classified = await self.classify(principal, ticket_id)
        return {
            **value,
            "category": classified["category"],
            "confidence": classified["confidence"],
        }

    async def _ground_step(self, value: dict[str, Any], context: StepContext) -> dict[str, Any]:
        """The retrieval capability as a step, so the draft can quote a passage."""
        principal, ticket_id = _call(value)
        return {**value, "grounding": await self.ground(principal, ticket_id)}

    async def _draft_step(self, value: dict[str, Any], context: StepContext) -> dict[str, Any]:
        """The drafting capability as a step: it writes a suggestion and nothing else."""
        principal, ticket_id = _call(value)
        suggestion = await self.draft(
            principal, ticket_id, grounding=str(value.get("grounding", ""))
        )
        return {**value, "suggestion": suggestion["id"]}

    async def _flag_step(self, value: dict[str, Any], context: StepContext) -> dict[str, Any]:
        """Leave the ticket classified and say why, instead of guessing at a draft."""
        principal, ticket_id = _call(value)
        detail = f"confidence={value['confidence']}: a person classifies this one"
        await self._tickets.record_event(principal, ticket_id, "flagged", detail)
        return value

    async def _record(
        self,
        principal: Principal,
        ticket_id: int,
        step: str,
        model: str,
        usage: Usage,
    ) -> None:
        """Write one usage row for a call the provider reported numbers for."""
        await self._usage.record(
            tenant=principal.tenant,
            ticket_id=ticket_id,
            step=step,
            model=model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )


def _call(value: Mapping[str, Any]) -> tuple[Principal, int]:
    """Return the principal and ticket id a step was given, refusing anything else."""
    principal = value["principal"]
    if not isinstance(principal, Principal):
        raise AssertionError("a workflow step was given something other than a principal")
    return principal, int(value["ticket"])
