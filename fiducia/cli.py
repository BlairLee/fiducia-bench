"""CLI: python -m fiducia.cli run --task tasks/seed/kyc-0003.yaml --script pipeline_lossy --arm D1"""
from __future__ import annotations
import argparse, json
from pathlib import Path
from .runner import load_task, load_pack, run_episode, save_trajectory
from .agents.base import ScriptedAgent
from .verify.checks import verify
from .verify.decomposition import decomposition_report


def main():
    ap = argparse.ArgumentParser(prog="fiducia")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--task", required=True)
    r.add_argument("--script", default="oracle")
    r.add_argument("--arm", default="D0")
    r.add_argument("--run-id", default="r1")
    r.add_argument("--out", default="results")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    task = load_task(root / args.task)
    pack = load_pack(root / task.policy_pack)
    if args.script not in task.scripts:
        raise SystemExit(f"no script '{args.script}' in {task.task_id}; "
                         f"available: {list(task.scripts)}")
    agent = ScriptedAgent(args.script, task.scripts[args.script])

    traj = run_episode(task, agent, root, run_id=args.run_id, arm=args.arm)
    save_trajectory(traj, root / args.out)
    verdict = verify(task, pack, traj, str(root / task.seed_db))
    report = {**verdict, "decomposition": decomposition_report(task, traj, verdict)}
    (root / args.out /
     f"{task.task_id}__{args.script}__{args.arm}__{args.run_id}.verdict.json"
     ).write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
