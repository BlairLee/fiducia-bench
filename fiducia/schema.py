"""Pydantic models for tasks, policies, and trajectories (machine-runnable subset of schema v0)."""
from __future__ import annotations
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class ToolSpec(BaseModel):
    """A pattern matching a tool call: tool name + optional arg constraints."""
    tool: str
    args_match: dict[str, Any] = Field(default_factory=dict)

    def matches(self, tool: str, args: dict[str, Any]) -> bool:
        if tool != self.tool:
            return False
        return all(args.get(k) == v for k, v in self.args_match.items())


class StateCond(BaseModel):
    """Condition over environment state. `path` is dot-notation into state.data."""
    path: str
    equals: Any = None
    contains: Any = None          # for lists; dict => match dict fields of any element
    exists: Optional[bool] = None

    def eval(self, state_data: dict[str, Any]) -> bool:
        node: Any = state_data
        for part in self.path.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                node = None
                break
        if self.exists is not None:
            return (node is not None) == self.exists
        if self.equals is not None:
            return node == self.equals
        if self.contains is not None:
            if node is None:
                return False
            if isinstance(self.contains, dict) and isinstance(node, list):
                return any(
                    isinstance(item, dict)
                    and all(item.get(k) == v for k, v in self.contains.items())
                    for item in node
                )
            return self.contains in node
        return node is not None


class PolicyCheck(BaseModel):
    type: Literal["allow_list", "require_before", "state_assert"]
    # require_before: `first` must occur before any call matching `then`
    first: Optional[ToolSpec] = None
    then: Optional[ToolSpec] = None
    # trigger: rule applies only when condition holds at the moment `then` is called
    trigger_state: Optional[StateCond] = None
    trigger_task_flag: Optional[str] = None
    # state_assert: at episode end, `assert_state` must hold whenever `when_state` holds
    when_state: Optional[StateCond] = None
    assert_state: Optional[StateCond] = None


class PolicyRule(BaseModel):
    rule_id: str
    text: str
    severity: Literal["critical", "major", "minor"]
    check: PolicyCheck


class PolicyPack(BaseModel):
    policy_pack: str
    rules: list[PolicyRule]


class SimRule(BaseModel):
    """Scripted simulator: if agent's last message matches any trigger substring, reply."""
    triggers: list[str]           # case-insensitive substrings
    reply: str
    reveals: list[str] = Field(default_factory=list)   # hidden_info ids revealed
    once: bool = True


class SimulatorSpec(BaseModel):
    opening: str
    rules: list[SimRule] = Field(default_factory=list)
    default_reply: str = "Okay — whatever you need."
    behavioral_style: str = "cooperative"


class Expectation(BaseModel):
    terminal_state: list[StateCond] = Field(default_factory=list)
    required_actions: list[ToolSpec] = Field(default_factory=list)
    forbidden_actions: list[ToolSpec] = Field(default_factory=list)
    escalation_required: bool = False
    escalation_target: Optional[str] = None


class Task(BaseModel):
    task_id: str
    track: str
    difficulty: str
    seed_db: str
    subject: str                  # primary customer id
    flags: list[str] = Field(default_factory=list)
    allow_tools: list[str]
    policy_pack: str
    simulator: SimulatorSpec
    expected: Expectation
    trigger_facts: list[TriggerFact] = Field(default_factory=list)
    constraint_distance: int = 0   # boundaries the fact must cross under decomposed arms
    # Scripted agents for pipeline validation (unused in LLM runs).
    # `scripts` holds named variants, e.g. oracle / naive / pipeline_faithful /
    # pipeline_lossy — the last two are multi-component and exercise attribution.
    scripts: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)


class ToolEvent(BaseModel):
    seq: int
    tool: str
    args: dict[str, Any]
    result: Any
    actor: str = "agent"          # which component issued the call


class Turn(BaseModel):
    role: Literal["user", "agent"]
    content: str = ""
    actor: str = "agent"
    tool_calls: list[ToolEvent] = Field(default_factory=list)


class Handoff(BaseModel):
    """A payload crossing a component boundary. First-class because fact attenuation
    is measured over exactly these objects."""
    seq: int
    src: str
    dst: str
    payload: str


class TriggerFact(BaseModel):
    """A machine-checkable fact that obliges a downstream action.

    `discovered_by` is the tool call that surfaces it; `obliges` is the action that
    must follow. `present_in` lists literal tokens whose appearance in a handoff
    payload counts as the fact having survived the boundary.
    """
    fact_id: str
    discovered_by: ToolSpec
    obliges: ToolSpec
    present_in: list[str] = Field(default_factory=list)


class Trajectory(BaseModel):
    task_id: str
    run_id: str
    agent_name: str
    turns: list[Turn] = Field(default_factory=list)
    arm: str = "D0"
    final_state: dict[str, Any] = Field(default_factory=dict)
    env_audit_log: list[dict[str, Any]] = Field(default_factory=list)
    handoffs: list[Handoff] = Field(default_factory=list)

    def tool_events(self) -> list[ToolEvent]:
        return [tc for t in self.turns for tc in t.tool_calls]

    def actors(self) -> list[str]:
        seen: list[str] = []
        for ev in self.tool_events():
            if ev.actor not in seen:
                seen.append(ev.actor)
        return seen
