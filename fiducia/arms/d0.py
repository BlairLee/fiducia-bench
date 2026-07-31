"""D0 — single ReAct loop. The baseline: one component, one context, no boundaries.

Constraint distance is 0 here by construction: whatever this component discovers, it
also decides on. Every governance failure under D0 is a reasoning failure, never a
propagation failure — which is exactly what makes it the control.
"""
from __future__ import annotations
from typing import Any

from ..agents.brain import Brain
from .base import ComponentContext, stamp


class D0Arm:
    arm_id = "D0"

    def __init__(self, brain: Brain, actor: str = "agent"):
        self.brain = brain
        self.actor = actor
        self.name = f"D0:{actor}"
        self._ctx = ComponentContext()

    def step(self, observation: dict[str, Any]) -> dict[str, Any]:
        action = self.brain.step(self._ctx.observe(self.actor, observation))
        if "handoff_payload" in action or "delegate" in action:
            raise ValueError("D0 has no boundaries: brain emitted a handoff/delegation")
        return self._ctx.record(stamp(action, self.actor), self.actor)
