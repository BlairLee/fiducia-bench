"""Episode runner: wires task + environment + simulator + agent, emits a Trajectory."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import yaml

from .schema import Task, PolicyPack, Trajectory, Turn, ToolEvent
from .env.state import EnvState
from .env import tools as toolmod
from .simulator.scripted import ScriptedSimulator
from .agents.base import ScriptedAgent

MAX_STEPS = 60


def load_task(path: str | Path) -> Task:
    with open(path) as f:
        return Task.model_validate(yaml.safe_load(f))


def load_pack(path: str | Path) -> PolicyPack:
    with open(path) as f:
        return PolicyPack.model_validate(yaml.safe_load(f))


def run_episode(task: Task, agent, repo_root: str | Path, run_id: str = "r1") -> Trajectory:
    root = Path(repo_root)
    state = EnvState(root / task.seed_db)
    sim = ScriptedSimulator(task.simulator)
    traj = Trajectory(task_id=task.task_id, run_id=run_id, agent_name=agent.name)

    traj.turns.append(Turn(role="user", content=sim.opening()))
    current_agent_turn = Turn(role="agent")

    for _ in range(MAX_STEPS):
        action = agent.step({"last_user_message": traj.turns[-1].content
                             if traj.turns[-1].role == "user" else None,
                             "state_public": {}})
        if action.get("done"):
            if current_agent_turn.content or current_agent_turn.tool_calls:
                traj.turns.append(current_agent_turn)
            break
        if "tool" in action:
            result = toolmod.call(state, action["tool"], action.get("args", {}))
            current_agent_turn.tool_calls.append(
                ToolEvent(seq=state.audit_log[-1]["seq"], tool=action["tool"],
                          args=action.get("args", {}), result=result))
        elif "message" in action:
            current_agent_turn.content = action["message"]
            traj.turns.append(current_agent_turn)
            reply = sim.respond(action["message"])
            traj.turns.append(Turn(role="user", content=reply))
            current_agent_turn = Turn(role="agent")

    traj.final_state = copy.deepcopy(state.data)
    traj.env_audit_log = list(state.audit_log)
    return traj


def save_trajectory(traj: Trajectory, out_dir: str | Path) -> Path:
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    p = out / f"{traj.task_id}__{traj.agent_name}__{traj.run_id}.json"
    p.write_text(traj.model_dump_json(indent=2))
    return p
