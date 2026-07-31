"""LLMBrain — a component's decisions, made by a model.

Implements the same `Brain` protocol as ScriptedBrain, so the arms are unchanged: the
topology, attribution and context isolation built and tested against scripted brains
apply verbatim to a model. What this class owns is one component's conversation with
one endpoint, and nothing else.
"""
from __future__ import annotations
import json
from typing import Any

from ...schema import LLMCall
from .client import LLMClient
from .parse import (assistant_message, finish_reason, parse_response, tool_call_id,
                    usage)

REPAIR_PROMPT = ("Your last response could not be used: {error}. Respond again, either "
                 "with a single tool call or with plain text for the customer.")


class LLMBrain:
    """One component, one model conversation.

    Every call is recorded in `call_log` — tokens, latency, and whether the response
    parsed. Parse failures are logged rather than swallowed: a malformed response and a
    deliberate refusal to act must never be scored as the same thing.
    """

    def __init__(self, name: str, client: LLMClient, system_prompt: str,
                 tools: list[dict[str, Any]] | None = None,
                 call_log: list[LLMCall] | None = None, max_repairs: int = 1):
        self.name = name
        self.client = client
        self.tools = tools or []
        self.call_log = call_log if call_log is not None else []
        self.max_repairs = max_repairs
        self.messages: list[dict[str, Any]] = [{"role": "system",
                                                "content": system_prompt}]
        self._pending_call: str | None = None
        self._last_inbox: str | None = None

    # ---- observation -> conversation ----

    def _ingest(self, observation: dict[str, Any]) -> None:
        refusal = observation.get("refusal")
        if refusal and self._pending_call:
            self._answer_call(f"refused: {refusal.get('reason', 'not available to you')}")
        result = observation.get("last_tool_result")
        if self._pending_call and result is not None:
            self._answer_call(json.dumps(result, default=str))

        inbox = observation.get("inbox")
        if inbox and inbox != self._last_inbox:
            self._last_inbox = inbox
            if self._pending_call:            # the answer to control_delegate
                self._answer_call(inbox)
            else:
                self.messages.append({"role": "user",
                                      "content": f"Handed to you:\n\n{inbox}"})

        user = observation.get("last_user_message")
        if user:
            self.messages.append({"role": "user", "content": f"Customer: {user}"})

    def _answer_call(self, content: str) -> None:
        self.messages.append({"role": "tool", "tool_call_id": self._pending_call,
                              "content": content})
        self._pending_call = None

    # ---- the step ----

    def step(self, observation: dict[str, Any]) -> dict[str, Any]:
        self._ingest(observation)
        for attempt in range(self.max_repairs + 1):
            response, latency_ms = self.client.chat(self.messages, self.tools)
            action, error = parse_response(response)
            self._log(response, latency_ms, error)
            if error is None:
                self.messages.append(assistant_message(response))
                if "tool" in action or "delegate" in action:
                    self._pending_call = tool_call_id(response)
                return action
            self.messages.append(assistant_message(response))
            self.messages.append({"role": "user",
                                  "content": REPAIR_PROMPT.format(error=error)})
        # Out of repairs. Stopping is the honest action: the component has produced
        # nothing usable, and the run is marked by the parse errors in the call log.
        return {"done": True}

    def _log(self, response: dict[str, Any], latency_ms: float,
             error: str | None) -> None:
        prompt_tokens, completion_tokens = usage(response)
        self.call_log.append(LLMCall(
            seq=len(self.call_log) + 1, actor=self.name, model=self.client.model,
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            latency_ms=round(latency_ms, 1), finish_reason=finish_reason(response),
            parse_error=error))

    @property
    def parse_failures(self) -> int:
        return sum(1 for c in self.call_log if c.parse_error)
