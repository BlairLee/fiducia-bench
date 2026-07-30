"""CLI: python -m fiducia.cli run --task tasks/seed/kyc-0001.yaml --agent oracle"""
from __future__ import annotations
import argparse, json
from pathlib import Path
from .runner import load_task, load_pack, run_episode, save_trajectory
from .agents.base import ScriptedAgent
from .verify.checks import verify


def main():
    ap = argparse.ArgumentParser(prog="fiducia")
    sub = ap.add_subparsers(dest="cmd", required=True)
    runp = sub.add_parser("run")
    runp.add_argument("--task", required=True)
    runp.add_argument("--agent", choices=["oracle", "naive"], default="oracle")
    runp.add_argument("--run-id", default="r1")
    runp.add_argument("--out", default="results")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    task = load_task(root / args.task)
    pack = load_pack(root / task.policy_pack)
    script = task.oracle_script if args.agent == "oracle" else task.naive_script
    agent = ScriptedAgent(args.agent, script)

    traj = run_episode(task, agent, root, run_id=args.run_id)
    p = save_trajectory(traj, root / args.out)
    verdict = verify(task, pack, traj, str(root / task.seed_db))
    (root / args.out / f"{task.task_id}__{args.agent}__{args.run_id}.verdict.json").write_text(
        json.dumps(verdict, indent=2))
    print(json.dumps(verdict, indent=2))


if __name__ == "__main__":
    main()
