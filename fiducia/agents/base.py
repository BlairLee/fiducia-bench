"""Agent interface + phase-1 scripted agents.

An agent step returns one of:
  {"message": str}                       -> say something to the user
  {"tool": str, "args": {...}}           -> call a tool
  {"done": True}                         -> end the episode

ScriptedAgent replays a fixed action list from the task YAML. Oracle scripts encode
the golden path; naive scripts encode the trap path. Their only job is to prove the
verifiers can tell them apart. LLM agents (phase 2) implement the same interface
against an OpenAI-compatible endpoint.
"""
from __future__ import annotations
from typing import Any


class ScriptedAgent:
    def __init__(self, name: str, script: list[dict[str, Any]]):
        self.name = name
        self._script = list(script)
        self._i = 0

    def step(self, observation: dict[str, Any]) -> dict[str, Any]:
        if self._i >= len(self._script):
            return {"done": True}
        action = self._script[self._i]
        self._i += 1
        return action


class OpenAICompatAgent:
    """Phase-2: same interface, backed by any OpenAI-compatible endpoint
    (local vLLM or cloud API). Deliberately unimplemented in phase 1."""

    def __init__(self, name: str, base_url: str, model: str, api_key: str = "EMPTY"):
        self.name = name
        self.base_url, self.model, self.api_key = base_url, model, api_key

    def step(self, observation: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("Phase 2: wire to /chat/completions with tool schemas")
