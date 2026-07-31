"""Episode runner: wires task + environment + simulator + agent, emits a Trajectory.

Agent actions (any arm) are one of:
  {"message": str, "actor": str?}                     -> speak to the user
  {"tool": str, "args": {...}, "actor": str?}         -> call a tool
  {"handoff": {"src":..,"dst":..,"payload":..}}       -> cross a component boundary
  {"done": True}

`actor` defaults to "agent" (the D0 single-loop case), so single-component arms need
no change. Attribution and handoff payloads are recorded by the ENVIRONMENT, so the
decomposition metrics never depend on the agent's self-report.
"""
from __future__ import annotations
import copy
from pathlib import Path
import yaml

from .schema import Task, PolicyPack, Trajectory, Turn, ToolEvent, Handoff, Reveal
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
    sim = ScriptedSimulator(task.simulator)
    traj = Trajectory(task_id=task.task_id, run_id=run_id,
                      agent_name=getattr(agent, "name", "agent"), arm=arm)

    traj.turns.append(Turn(role="user", content=sim.opening()))
    pending = Turn(role="agent")

    for _ in range(MAX_STEPS):
        action = agent.step({
            "last_user_message": traj.turns[-1].content
            if traj.turns[-1].role == "user" else None,
            "state_public": {},
        })
        if action.get("done"):
            break

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
            pending = Turn(role="agent", actor=actor)

    if pending.content or pending.tool_calls:
        traj.turns.append(pending)

    traj.final_state = copy.deepcopy(state.data)
    traj.env_audit_log = list(state.audit_log)
    return traj


def save_trajectory(traj: Trajectory, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"{traj.task_id}__{traj.agent_name}__{traj.arm}__{traj.run_id}.json"
    p.write_text(traj.model_dump_json(indent=2))
    return p
