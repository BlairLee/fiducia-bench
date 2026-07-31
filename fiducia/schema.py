"""Pydantic models for tasks, policies, and trajectories (machine-runnable subset of schema v0)."""
from __future__ import annotations
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, model_validator


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
    type: Literal["allow_list", "require_before", "state_assert", "forbid_when"]
    # require_before: `first` must occur before any call matching `then`
    # forbid_when:    `then` may not be called at all while the trigger holds
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

    Discovery is either a tool call (`discovered_by`) or a disclosure by the user
    simulator (`discovered_by_reveal`, naming a `SimRule.reveals` id). The latter
    exists because some obligations are triggered by what the agent *elicited*, not
    by what a tool returned — and the simulator is part of the environment, so that
    discovery is still attributable without trusting the agent's self-report.

    The obligation is either positive (`obliges`: this action must follow) or negative
    (`forbids`: this action must NOT be taken). Negative facts are exculpating — an
    identity mismatch that resolves an apparent hit — and they fail in the opposite
    direction: when the exculpating half does not survive a boundary, the deciding
    component over-reacts. Same mechanism, mirrored outcome, so both are scored as
    `propagation_loss`.

    `present_in` lists literal tokens whose appearance in a handoff payload counts as
    the fact having survived the boundary.

    `depends_on` chains facts: fact B's discovery is only reachable if fact A's
    obligation was carried out. It lets the metrics distinguish "this component
    dropped the fact" from "the fact never reached this component at all".
    """
    fact_id: str
    discovered_by: Optional[ToolSpec] = None
    discovered_by_reveal: Optional[str] = None
    obliges: Optional[ToolSpec] = None
    forbids: Optional[ToolSpec] = None
    present_in: list[str] = Field(default_factory=list)
    depends_on: Optional[str] = None

    @property
    def obligated_action(self) -> ToolSpec:
        """The action the fact bears on, whichever direction it points."""
        return self.obliges or self.forbids   # type: ignore[return-value]

    @property
    def direction(self) -> str:
        return "obliges" if self.obliges is not None else "forbids"

    @model_validator(mode="after")
    def _exactly_one_of_each(self) -> "TriggerFact":
        if (self.discovered_by is None) == (self.discovered_by_reveal is None):
            raise ValueError(
                f"{self.fact_id}: set exactly one of discovered_by / discovered_by_reveal")
        if (self.obliges is None) == (self.forbids is None):
            raise ValueError(f"{self.fact_id}: set exactly one of obliges / forbids")
        return self


class BlockedCall(BaseModel):
    """A tool call an ARM refused because the component's scope excludes it.

    It never reaches the environment, so it is not a policy violation — the tool was
    simply not available to that component. It is recorded because "the component that
    found the problem had no authority to act on it" is a governance finding, and one
    that leaves no other trace.
    """
    seq: int
    actor: str
    tool: str
    reason: str


class Reveal(BaseModel):
    """Hidden info the simulator disclosed in response to an agent's question.

    Recorded by the environment (the simulator is environment-side), with the actor
    that asked, so elicitation can trigger obligations the same way a tool result can.
    """
    seq: int
    info_id: str
    actor: str


class Trajectory(BaseModel):
    task_id: str
    run_id: str
    agent_name: str
    turns: list[Turn] = Field(default_factory=list)
    arm: str = "D0"
    final_state: dict[str, Any] = Field(default_factory=dict)
    env_audit_log: list[dict[str, Any]] = Field(default_factory=list)
    handoffs: list[Handoff] = Field(default_factory=list)
    reveals: list[Reveal] = Field(default_factory=list)
    blocked_calls: list[BlockedCall] = Field(default_factory=list)

    def tool_events(self) -> list[ToolEvent]:
        return [tc for t in self.turns for tc in t.tool_calls]

    def actors(self) -> list[str]:
        seen: list[str] = []
        for ev in self.tool_events():
            if ev.actor not in seen:
                seen.append(ev.actor)
        return seen
