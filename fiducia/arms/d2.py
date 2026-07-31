"""D2 — orchestrator delegating to subagents with narrowed tool scopes.

Two boundaries per delegation, both logged: the brief going down and the summary coming
back. Both are places a policy-relevant fact can fail to appear.

Tool scope is a property of the ARCHITECTURE, not of the task's allow-list. A subagent
reaching for a tool outside its scope is refused by the arm — the call never reaches the
environment, so it is not a TOOL-ALLOW violation. It is recorded anyway: "the component
that found the problem had no authority to act on it" is precisely the escalation-
diffusion story, and it is invisible unless the attempt is written down.
"""
from __future__ import annotations
from typing import Any

from ..agents.brain import Brain
from .base import ComponentContext, blocked, stamp

ORCHESTRATOR = "orchestrator"


class D2Arm:
    arm_id = "D2"

    def __init__(self, orchestrator: Brain,
                 subagents: dict[str, tuple[Brain, list[str]]],
                 orchestrator_name: str = ORCHESTRATOR):
        self.orchestrator = orchestrator
        self.subagents = subagents
        self.orchestrator_name = orchestrator_name
        self.name = f"D2:{orchestrator_name}+" + "+".join(sorted(subagents))
        self._active: str | None = None       # None = the orchestrator has the floor
        self._inbox: dict[str, str | None] = {}
        self._ctx = ComponentContext()

    @property
    def actor(self) -> str:
        return self._active or self.orchestrator_name

    def _scope(self) -> list[str] | None:
        return self.subagents[self._active][1] if self._active else None

    def step(self, observation: dict[str, Any]) -> dict[str, Any]:
        actor = self.actor
        brain = self.subagents[self._active][0] if self._active else self.orchestrator
        action = brain.step(self._ctx.observe(
            actor, observation, inbox=self._inbox.get(actor), scope=self._scope()))

        if self._active is None:
            return self._orchestrator_action(action, actor)
        return self._subagent_action(action, actor)

    def _orchestrator_action(self, action: dict[str, Any], actor: str) -> dict[str, Any]:
        if "delegate" in action:
            dst = str(action["delegate"])
            if dst not in self.subagents:
                raise ValueError(f"no such subagent: {dst}")
            brief = str(action.get("brief", ""))
            self._active = dst
            self._inbox[dst] = brief
            self._ctx.cross_boundary()
            return {"handoff": {"src": actor, "dst": dst, "payload": brief}}
        return self._ctx.record(stamp(action, actor), actor)

    def _subagent_action(self, action: dict[str, Any], actor: str) -> dict[str, Any]:
        scope = self._scope() or []
        if "tool" in action and action["tool"] not in scope:
            return blocked(actor, str(action["tool"]),
                           f"outside {actor} tool scope {sorted(scope)}")

        # A subagent that reports back — or simply stops — returns the floor. Stopping
        # without a payload is a silent boundary, and it is left visible as one.
        if "handoff_payload" in action or action.get("done"):
            payload = str(action.get("handoff_payload", ""))
            self._active = None
            self._inbox[self.orchestrator_name] = payload
            self._ctx.cross_boundary()
            return {"handoff": {"src": actor, "dst": self.orchestrator_name,
                                "payload": payload}}

        return self._ctx.record(stamp(action, actor), actor)
