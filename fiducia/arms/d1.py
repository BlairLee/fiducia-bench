"""D1 — fixed pipeline. Sequential stages, no dynamic routing.

The defining property: **a stage receives only the previous stage's handoff payload.**
Not its tool results, not the transcript, not what the user said before it existed. That
is the whole mechanism under study, so the arm enforces it structurally rather than by
asking a prompt nicely — a stage physically cannot see upstream context here.

A stage advances the pipeline by emitting `handoff_payload`. Emitting `done` ends the
episode wherever it happens, which is itself a governable behaviour: a middle stage that
finishes without handing anything on has dropped everything it knew.
"""
from __future__ import annotations
from typing import Any

from ..agents.brain import Brain
from .base import ComponentContext, stamp


class D1Arm:
    arm_id = "D1"

    def __init__(self, stages: list[tuple[str, Brain]]):
        if not stages:
            raise ValueError("D1 needs at least one stage")
        self.stages = stages
        self.name = "D1:" + ">".join(n for n, _ in stages)
        self._i = 0
        self._inbox: str | None = None
        self._ctx = ComponentContext()

    @property
    def actor(self) -> str:
        return self.stages[self._i][0]

    def step(self, observation: dict[str, Any]) -> dict[str, Any]:
        actor = self.actor
        action = self.stages[self._i][1].step(
            self._ctx.observe(actor, observation, inbox=self._inbox))

        if "handoff_payload" in action:
            payload = str(action["handoff_payload"])
            if self._i + 1 >= len(self.stages):
                return {"done": True}          # last stage has nobody to hand to
            dst = self.stages[self._i + 1][0]
            self._i += 1
            self._inbox = payload
            self._ctx.cross_boundary()
            return {"handoff": {"src": actor, "dst": dst, "payload": payload}}

        return self._ctx.record(stamp(action, actor), actor)
