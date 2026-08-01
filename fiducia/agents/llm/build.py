"""Assemble a runnable arm for (task, arm, policy mode, model).

One place where the grid's cells become objects. Everything an arm needs that is not
already in the task YAML is decided here, which is also where it can be inspected and
published: stage names, subagent rosters, and the tool scopes D2 narrows to.

Two constraints hold across arms, and both are the point of the experiment:
  - every component sees the SAME tool descriptions and the SAME policy corpus;
  - only the topology and the prompt paragraph describing it differ.
"""
from __future__ import annotations
from typing import Any

from ...arms import D0Arm, D1Arm, D2Arm
from ...schema import LLMCall, PolicyPack, Task
from . import prompts
from .brain import LLMBrain
from .client import LLMClient
from .schema import tools_for

# D1's instantiation: first stage owns customer contact, middle owns lookups, last owns
# the decision. Every stage keeps the task's full tool list — D1 differs from D0 in
# CONTEXT only, which is what isolates decomposition from tool availability.
D1_STAGES = ("intake", "research", "decide")

# D2 narrows scopes, because that is what the architecture is. The split is derived, not
# hand-written per task: anything that only reads is delegable, anything that changes
# the world stays with the orchestrator.
READ_ONLY_TOOLS = ("customer_db.read", "kyc_screening.run", "business_registry.lookup",
                   "policy_lookup.search")
D2_SUBAGENT = "researcher"


def _scope(task: Task, tools: tuple[str, ...]) -> list[str]:
    return [t for t in task.allow_tools if t in tools]


def build_arm(task: Task, pack: PolicyPack, arm_id: str, client: LLMClient,
              policy_mode: str = "P0",
              call_log: list[LLMCall] | None = None) -> Any:
    log: list[LLMCall] = call_log if call_log is not None else []
    arm = _build(task, pack, arm_id, client, policy_mode, log)
    # picked up by run_episode; keeps cost + fingerprint on the trajectory
    arm.call_log = log
    arm.model_fingerprint = {**client.fingerprint(), "policy_mode": policy_mode,
                             "arm": arm_id}
    return arm


def _build(task: Task, pack: PolicyPack, arm_id: str, client: LLMClient,
           policy_mode: str, log: list[LLMCall]) -> Any:
    if arm_id == "D0":
        return D0Arm(LLMBrain(
            "agent", client, prompts.d0_prompt(task, pack, policy_mode),
            tools_for(task.allow_tools), call_log=log))

    if arm_id == "D1":
        stages = list(D1_STAGES)
        return D1Arm([
            (name, LLMBrain(
                name, client, prompts.d1_prompt(task, pack, stages, i, policy_mode),
                tools_for(task.allow_tools, can_handoff=i < len(stages) - 1),
                call_log=log))
            for i, name in enumerate(stages)
        ])

    if arm_id == "D2":
        scope = _scope(task, READ_ONLY_TOOLS)
        roster = {D2_SUBAGENT: scope}
        orchestrator = LLMBrain(
            "orchestrator", client,
            prompts.d2_orchestrator_prompt(task, pack, roster, policy_mode),
            tools_for(task.allow_tools, delegates=[D2_SUBAGENT]), call_log=log)
        sub = LLMBrain(
            D2_SUBAGENT, client,
            prompts.d2_subagent_prompt(task, pack, D2_SUBAGENT, scope, policy_mode),
            tools_for(scope, can_handoff=True), call_log=log)
        return D2Arm(orchestrator, {D2_SUBAGENT: (sub, scope)})

    raise ValueError(f"unknown arm: {arm_id}")
