"""Phase-1 scripted user simulator.

The user's replies are driven by trigger rules from the task YAML: hidden info is
revealed only when the agent's message matches a trigger. This is the deterministic
stand-in for the LLM simulator (phase 2), sharing the same interface.
"""
from __future__ import annotations
from ..schema import SimulatorSpec


class ScriptedSimulator:
    def __init__(self, spec: SimulatorSpec):
        self.spec = spec
        self._used: set[int] = set()
        self.revealed: set[str] = set()
        self.last_reveals: list[str] = []   # ids disclosed by the most recent respond()

    def opening(self) -> str:
        return self.spec.opening

    def respond(self, agent_message: str) -> str:
        msg = agent_message.lower()
        self.last_reveals = []
        for i, rule in enumerate(self.spec.rules):
            if rule.once and i in self._used:
                continue
            if any(t.lower() in msg for t in rule.triggers):
                self._used.add(i)
                self.last_reveals = [r for r in rule.reveals if r not in self.revealed]
                self.revealed.update(rule.reveals)
                return rule.reply
        return self.spec.default_reply
