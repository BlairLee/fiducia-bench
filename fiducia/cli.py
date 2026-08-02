"""CLI.

  run       replay a task's fixture script:
            python -m fiducia.cli run --task tasks/seed/kyc-0003.yaml --script oracle
  run-llm   drive an arm with a real model over an OpenAI-compatible endpoint:
            python -m fiducia.cli run-llm --task tasks/seed/kyc-0003.yaml --arm D1 \
                --base-url http://localhost:8000/v1 --model qwen3-30b
"""
from __future__ import annotations
import argparse, json, os
from pathlib import Path
from .runner import load_task, load_pack, run_episode, save_trajectory, slug
from .agents.base import ScriptedAgent
from .verify.checks import verify
from .verify.decomposition import decomposition_report


def _score(task, pack, traj, root, out_dir, label):
    save_trajectory(traj, out_dir)
    verdict = verify(task, pack, traj, str(root / task.seed_db))
    report = {**verdict, "truncated": traj.truncated,
              "decomposition": decomposition_report(task, traj, verdict)}
    if traj.llm_calls:
        report["cost"] = cost_summary(traj)
    (out_dir / f"{slug(label)}.verdict.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return report


def cost_summary(traj) -> dict:
    """Per-episode cost, which is what sizes the pilot. Reported per actor because the
    whole question is whether decomposed arms cost more per unit of governance."""
    per_actor: dict[str, dict] = {}
    for c in traj.llm_calls:
        a = per_actor.setdefault(c.actor, {"calls": 0, "prompt_tokens": 0,
                                           "completion_tokens": 0})
        a["calls"] += 1
        a["prompt_tokens"] += c.prompt_tokens
        a["completion_tokens"] += c.completion_tokens
    return {
        "calls": len(traj.llm_calls),
        "prompt_tokens": sum(c.prompt_tokens for c in traj.llm_calls),
        "completion_tokens": sum(c.completion_tokens for c in traj.llm_calls),
        "latency_ms": round(sum(c.latency_ms for c in traj.llm_calls), 1),
        "parse_failures": sum(1 for c in traj.llm_calls if c.parse_error),
        "per_actor": per_actor,
    }


def main():
    ap = argparse.ArgumentParser(prog="fiducia")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="replay a fixture script")
    r.add_argument("--task", required=True)
    r.add_argument("--script", default="oracle")
    r.add_argument("--arm", default="D0")
    r.add_argument("--run-id", default="r1")
    r.add_argument("--out", default="results")

    m = sub.add_parser("run-llm", help="drive an arm with a model")
    m.add_argument("--task", required=True)
    m.add_argument("--arm", default="D0", choices=["D0", "D1", "D2"])
    m.add_argument("--policy", default="P0", choices=["P0", "P1"])
    m.add_argument("--base-url", default=os.environ.get("FIDUCIA_BASE_URL",
                                                        "http://localhost:8000/v1"))
    m.add_argument("--model", default=os.environ.get("FIDUCIA_MODEL", "local"))
    m.add_argument("--api-key", default=os.environ.get("FIDUCIA_API_KEY", "EMPTY"))
    m.add_argument("--temperature", type=float, default=0.0)
    m.add_argument("--seed", type=int, default=0)
    m.add_argument("--max-tokens", type=int, default=1024)
    # Endpoint-specific body fields, e.g. turning off a reasoning model's thinking mode:
    #   --extra-json '{"chat_template_kwargs": {"enable_thinking": false}}'
    # Anything passed here lands in the model fingerprint, because anything that changes
    # the distribution episodes were drawn from has to be recorded with them.
    m.add_argument("--extra-json", default="{}")
    m.add_argument("--max-steps", type=int, default=40,
                   help="hard cap on agent actions; an episode that never finishes "
                        "otherwise costs a full budget of model calls")
    m.add_argument("--sim-model", default=None,
                   help="model for the LLM user simulator (default: use scripted)")
    m.add_argument("--sim-base-url", default=None,
                   help="endpoint for the simulator model (default: same as --base-url)")
    m.add_argument("--run-id", default="r1")
    m.add_argument("--out", default="results")

    a = sub.add_parser("aggregate", help="summarise a sweep's JSONL into stats + table")
    a.add_argument("input", help="path to sweep .jsonl file")
    a.add_argument("--json", dest="json_out", default=None,
                   help="write full aggregation to this JSON file")

    args = ap.parse_args()
    root = Path(__file__).resolve().parent.parent

    if args.cmd == "aggregate":
        from .aggregate import load_episodes, aggregate, print_table
        episodes = load_episodes(args.input)
        agg = aggregate(episodes)
        print_table(agg)
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(agg, indent=2))
            print(f"Written to {args.json_out}")
        return

    task = load_task(root / args.task)
    pack = load_pack(root / task.policy_pack)
    out_dir = root / args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.cmd == "run":
        if args.script not in task.scripts:
            raise SystemExit(f"no script '{args.script}' in {task.task_id}; "
                             f"available: {list(task.scripts)}")
        agent = ScriptedAgent(args.script, task.scripts[args.script])
        traj = run_episode(task, agent, root, run_id=args.run_id, arm=args.arm)
        _score(task, pack, traj, root, out_dir,
               f"{task.task_id}__{args.script}__{args.arm}__{args.run_id}")
        return

    from .agents.llm import LLMClient, build_arm
    client = LLMClient(args.base_url, args.model, api_key=args.api_key,
                       temperature=args.temperature, seed=args.seed,
                       max_tokens=args.max_tokens,
                       extra=json.loads(args.extra_json))
    arm = build_arm(task, pack, args.arm, client, policy_mode=args.policy)
    sim = None
    if getattr(args, "sim_model", None):
        from .simulator.llm import LLMSimulator
        sim_client = LLMClient(
            args.sim_base_url or args.base_url, args.sim_model,
            api_key=args.api_key, temperature=0.0, seed=0, max_tokens=256)
        sim = LLMSimulator(task.simulator, sim_client)
    traj = run_episode(task, arm, root, run_id=args.run_id,
                       max_steps=args.max_steps, simulator=sim)
    _score(task, pack, traj, root, out_dir,
           f"{task.task_id}__{args.arm}x{args.policy}__{args.model}__{args.run_id}")


if __name__ == "__main__":
    main()
