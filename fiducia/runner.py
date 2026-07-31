"""Episode runner: wires task + environment + simulator + agent, emits a Trajectory.

Agent actions (any arm) are one of:
  {"message": str, "actor": str?}                     -> speak to the user
  {"tool": str, "args": {...}, "actor": str?}         -> call a tool
  {"handoff": {"src":..,"dst":..,"payload":..}}       -> cross a component boundary
  {"blocked": {"actor":..,"tool":..,"reason":..}}     -> arm refused an out-of-scope call
  {"done": True}

`actor` defaults to "agent" (the D0 single-loop case), so single-component arms need
no change. Attribution and handoff payloads are recorded by the ENVIRONMENT, so the
decomposition metrics never depend on the agent's self-report.

The runner does not know about arms: an `Arm` is just an agent that composes component
brains and stamps attribution on their behalf (see `fiducia/arms/`). Keeping the runner
arm-agnostic is what guarantees arms differ only in orchestration.
"""
from __future__ import annotations
import copy
from pathlib import Path
from typing import Any
import yaml

from .schema import (Task, PolicyPack, Trajectory, Turn, ToolEvent, Handoff, Reveal,
                     BlockedCall)
from .env.state import EnvState
from .env import tools as toolmod
from .simulator.scripted import ScriptedSimulator

MAX_STEPS = 120


def load_task(path: str | Path) -> Task:
    with open(path) as f:
        return Task.model_validate(yaml.safe_load(f))


def load_pack(path: str | Path) -> PolicyPack:
    with open(path) as f:
        return PolicyPack.model_validate(yaml.safe_load(f))


def run_episode(task: Task, agent, repo_root: str | Path, run_id: str = "r1",
                arm: str = "D0") -> Trajectory:
    root = Path(repo_root)
    state = EnvState(root / task.seed_db)
    # Factor P demands one corpus, two access modes: P0 pastes the policy pack into
    # context, P1 leaves it retrievable through `policy_lookup.search`. If the tool
    # searched the seed DB's abridged notes instead, P0 vs P1 would differ in policy
    # CONTENT as well as access, and the comparison would mean nothing.
    pack_path = root / task.policy_pack
    if pack_path.exists():
        state.data["_policy_texts"] = [
            {"rule_id": r.rule_id, "text": r.text.strip()}
            for r in load_pack(pack_path).rules
        ]
    sim = ScriptedSimulator(task.simulator)
    # An arm knows its own topology; trust that over the caller's label so a trajectory
    # can never be filed under an architecture it did not actually run.
    traj = Trajectory(task_id=task.task_id, run_id=run_id,
                      agent_name=getattr(agent, "name", "agent"),
                      arm=getattr(agent, "arm_id", arm))

    traj.turns.append(Turn(role="user", content=sim.opening()))
    pending = Turn(role="agent")
    last_tool_result: Any = None
    user_turns = 1

    for _ in range(MAX_STEPS):
        action = agent.step({
            "last_user_message": traj.turns[-1].content
            if traj.turns[-1].role == "user" else None,
            # lets an arm deliver a reply once, to the component that asked for it
            "user_turn_seq": user_turns,
            "last_tool_result": last_tool_result,
            "state_public": {},
        })
        if action.get("done"):
            break

        if "blocked" in action:
            b = action["blocked"]
            seq = state.log_blocked(b["actor"], b["tool"], b.get("reason", ""))
            traj.blocked_calls.append(BlockedCall(seq=seq, **b))
            continue

        if "handoff" in action:
            h = action["handoff"]
            payload = str(h.get("payload", ""))
            seq = state.log_handoff(h.get("src", "?"), h.get("dst", "?"), payload)
            traj.handoffs.append(Handoff(seq=seq, src=h.get("src", "?"),
                                         dst=h.get("dst", "?"), payload=payload))
            continue

        actor = action.get("actor", "agent")

        if "tool" in action:
            if pending.tool_calls and pending.actor != actor:
                traj.turns.append(pending)
                pending = Turn(role="agent", actor=actor)
            pending.actor = actor
            result = toolmod.call(state, action["tool"], action.get("args", {}),
                                  actor=actor)
            last_tool_result = result
            pending.tool_calls.append(
                ToolEvent(seq=state.audit_log[-1]["seq"], tool=action["tool"],
                          args=action.get("args", {}), result=result, actor=actor))

        elif "message" in action:
            pending.actor = actor
            pending.content = action["message"]
            traj.turns.append(pending)
            reply = sim.respond(action["message"])
            # Hidden info disclosed in reply to THIS component's question. Logged by the
            # environment so elicitation is attributable, like any tool call.
            for info_id in sim.last_reveals:
                seq = state.log_reveal(info_id, actor=actor)
                traj.reveals.append(Reveal(seq=seq, info_id=info_id, actor=actor))
            traj.turns.append(Turn(role="user", content=reply))
            user_turns += 1
            pending = Turn(role="agent", actor=actor)

    if pending.content or pending.tool_calls:
        traj.turns.append(pending)

    traj.final_state = copy.deepcopy(state.data)
    traj.env_audit_log = list(state.audit_log)
    # Cost model and parse-failure rate belong to the trajectory, not to a side channel,
    # so historical runs can be re-scored on both.
    traj.llm_calls = list(getattr(agent, "call_log", None) or [])
    traj.model_fingerprint = dict(getattr(agent, "model_fingerprint", None) or {})
    return traj


def save_trajectory(traj: Trajectory, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"{traj.task_id}__{traj.agent_name}__{traj.arm}__{traj.run_id}.json"
    p.write_text(traj.model_dump_json(indent=2))
    return p
