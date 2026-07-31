"""A `Brain` is the decision-making half of a component; an `Arm` is the topology half.

Splitting them is what makes the experiment an experiment. The arm decides who exists,
what each one can see, what crosses the boundaries between them, and who gets attributed
for a call. The brain decides only what to do next. Swap ScriptedBrain for an LLM brain
and the topology — and every governance property that depends on it — is unchanged.

A brain may return:
  {"message": str}                  say something to the user
  {"tool": str, "args": {...}}      call a tool
  {"handoff_payload": str}          "I'm finished — this is what I'm passing on"
  {"delegate": str, "brief": str}   orchestrator only: hand work to a named subagent
  {"done": True}                    end the episode

Note what is NOT in that list: `actor`, and any control over handoff routing. A component
cannot name itself or choose who it reports to. See `arms/base.py::stamp`.
"""
from __future__ import annotations
from typing import Any, Protocol


class Brain(Protocol):
    name: str

    def step(self, observation: dict[str, Any]) -> dict[str, Any]: ...


class ScriptedBrain:
    """Replays a fixed action list for ONE component.

    The phase-1 stand-in for an LLM brain, used to unit-test attribution, context
    isolation and tool scoping without a model in the loop. Actions are per-component:
    unlike the flat task-YAML `scripts:`, they carry no actor and no handoff routing.
    """

    def __init__(self, name: str, actions: list[dict[str, Any]]):
        self.name = name
        self._actions = list(actions)
        self._i = 0

    def step(self, observation: dict[str, Any]) -> dict[str, Any]:
        if self._i >= len(self._actions):
            return {"done": True}
        action = self._actions[self._i]
        self._i += 1
        return dict(action)

    @property
    def exhausted(self) -> bool:
        return self._i >= len(self._actions)
