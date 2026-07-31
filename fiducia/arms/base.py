"""Shared arm machinery: attribution stamping and observation assembly.

The arm is trusted orchestration code; the brain is the thing under test. Everything
here exists to keep that boundary honest — most importantly, `stamp`.
"""
from __future__ import annotations
from typing import Any, Protocol

# The only keys a brain may express. Anything else it emits — `actor` above all — is
# discarded before the action reaches the runner.
BRAIN_KEYS = frozenset({"message", "tool", "args", "handoff_payload",
                        "delegate", "brief", "done"})


class Arm(Protocol):
    arm_id: str
    name: str

    def step(self, observation: dict[str, Any]) -> dict[str, Any]: ...


def stamp(action: dict[str, Any], actor: str) -> dict[str, Any]:
    """Return the action with attribution applied by the TOPOLOGY.

    A component does not get to say who it is. Whatever the brain emitted, the actor
    recorded against the call is the one the arm assigned — so a model that writes
    `{"actor": "compliance_officer"}` into its output changes nothing. This is the
    same principle as the environment owning the audit log, applied one level up:
    attribution is a property of the architecture, not a claim by the component.
    """
    out = {k: v for k, v in action.items() if k in BRAIN_KEYS}
    if "tool" in out or "message" in out:
        out["actor"] = actor
    return out


class ComponentContext:
    """Per-component view of the runner's shared observation.

    Context isolation lives here, and it has to be enforced rather than assumed: the
    runner reports the last tool result and the last user message globally, so an arm
    that passed them straight through would leak one component's findings to the next
    and quietly destroy the very effect the benchmark measures. A component sees a tool
    result only if IT made the call, and a user reply only if it was active when the
    reply arrived.
    """

    def __init__(self) -> None:
        self._tool_actor: str | None = None
        self._pending_user: str | None = None
        self._seen_user_turn = -1

    def observe(self, actor: str, observation: dict[str, Any], *,
                inbox: str | None = None,
                scope: list[str] | None = None) -> dict[str, Any]:
        turn = observation.get("user_turn_seq", -1)
        if turn > self._seen_user_turn:
            self._seen_user_turn = turn
            self._pending_user = observation.get("last_user_message")
        user, self._pending_user = self._pending_user, None
        return {
            "inbox": inbox,
            "last_user_message": user,
            "last_tool_result": (observation.get("last_tool_result")
                                 if self._tool_actor == actor else None),
            "tool_scope": scope,
        }

    def record(self, action: dict[str, Any], actor: str) -> dict[str, Any]:
        """Note who made a tool call, so its result stays with them."""
        if "tool" in action:
            self._tool_actor = actor
        return action

    def cross_boundary(self) -> None:
        """Nothing but the payload crosses: not pending user replies, not tool results."""
        self._tool_actor = None
        self._pending_user = None


def blocked(actor: str, tool: str, reason: str) -> dict[str, Any]:
    """An action the arm refused. Recorded by the environment, never executed."""
    return {"blocked": {"actor": actor, "tool": tool, "reason": reason}}
