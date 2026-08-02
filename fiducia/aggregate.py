"""Aggregation: sweep results → per-cell statistics → headline figure data.

The headline figure is governance failure rate vs constraint_distance, one line
per arm. Everything here is a pure function of the episode records — no side
effects, no network, no model calls.

Input: a list of episode dicts (one per JSONL line from a sweep).
Output: a nested summary keyed by (arm, distance) with pass rates, confidence
intervals, cost, and the mechanism indicators (attenuation, propagation loss).

pass^k: the probability that at least one of k independent runs of the same
(task, arm) cell succeeds. Estimated as 1 - (1 - p)^k where p is the per-run
governed_success rate for that cell. This is the standard metric for agent
benchmarks (SWE-bench, τ-bench) and allows cost/reliability tradeoffs.
"""
from __future__ import annotations
import math
from collections import defaultdict
from typing import Any


def load_episodes(path: str) -> list[dict[str, Any]]:
    import json
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def _rate(hits: int, total: int) -> float:
    return hits / total if total else 0.0


def _ci95(p: float, n: int) -> tuple[float, float]:
    """Wilson score 95% confidence interval for a binomial proportion."""
    if n == 0:
        return (0.0, 1.0)
    z = 1.96
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    spread = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return (max(0.0, centre - spread), min(1.0, centre + spread))


def _pass_at_k(p: float, k: int) -> float:
    """Probability of at least one success in k independent trials."""
    return 1.0 - (1.0 - p) ** k


def cell_summary(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Statistics for one (arm, distance) or (arm, task) cell."""
    n = len(episodes)
    if n == 0:
        return {"n": 0}

    gov = sum(e["governed_success"] for e in episodes)
    trunc = sum(e["truncated"] for e in episodes)
    esc_correct = sum(e["esc_correct"] for e in episodes)
    att = sum(e["attenuation"] for e in episodes)
    ploss = sum(e["prop_loss"] for e in episodes)
    p = _rate(gov, n)

    return {
        "n": n,
        "governed_success": gov,
        "gov_rate": round(p, 3),
        "gov_ci95": [round(x, 3) for x in _ci95(p, n)],
        "pass_at_2": round(_pass_at_k(p, 2), 3),
        "pass_at_3": round(_pass_at_k(p, 3), 3),
        "truncated": trunc,
        "truncation_rate": round(_rate(trunc, n), 3),
        "escalation_correct": esc_correct,
        "esc_accuracy": round(_rate(esc_correct, n), 3),
        "attenuation": att,
        "attenuation_rate": round(_rate(att, n), 3),
        "propagation_loss": ploss,
        "prop_loss_rate": round(_rate(ploss, n), 3),
        "violations": _violation_counts(episodes),
        "mean_calls": round(sum(e["calls"] for e in episodes) / n, 1),
        "mean_prompt_tokens": round(sum(e["prompt_tokens"] for e in episodes) / n, 0),
        "mean_wall_s": round(sum(e["wall_s"] for e in episodes) / n, 1),
        "parse_failures": sum(e["parse_failures"] for e in episodes),
    }


def _violation_counts(episodes: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for e in episodes:
        for v in e.get("violations", []):
            counts[v] += 1
    return dict(sorted(counts.items()))


def aggregate(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Full aggregation: by arm, by distance, and the arm×distance grid."""
    by_arm: dict[str, list] = defaultdict(list)
    by_dist: dict[int, list] = defaultdict(list)
    by_cell: dict[tuple[str, int], list] = defaultdict(list)
    by_task: dict[tuple[str, str], list] = defaultdict(list)

    for e in episodes:
        arm, dist = e["arm"], e.get("distance", 0)
        by_arm[arm].append(e)
        by_dist[dist].append(e)
        by_cell[(arm, dist)].append(e)
        by_task[(e["task"], arm)].append(e)

    return {
        "total_episodes": len(episodes),
        "by_arm": {arm: cell_summary(eps) for arm, eps in sorted(by_arm.items())},
        "by_distance": {str(d): cell_summary(eps)
                        for d, eps in sorted(by_dist.items())},
        "grid": {f"{arm}×d{dist}": cell_summary(eps)
                 for (arm, dist), eps in sorted(by_cell.items())},
        "by_task": {f"{task}×{arm}": cell_summary(eps)
                    for (task, arm), eps in sorted(by_task.items())},
        "headline": headline_figure_data(episodes),
    }


def headline_figure_data(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Data for the headline figure: gov failure rate vs distance, one series per arm.

    Returns {arm: [{distance, failure_rate, ci_lo, ci_hi, n}, ...]} sorted by distance.
    """
    by_cell: dict[tuple[str, int], list] = defaultdict(list)
    for e in episodes:
        by_cell[(e["arm"], e.get("distance", 0))].append(e)

    series: dict[str, list] = defaultdict(list)
    for (arm, dist), eps in sorted(by_cell.items()):
        n = len(eps)
        p = _rate(sum(e["governed_success"] for e in eps), n)
        lo, hi = _ci95(1 - p, n)  # failure rate CI
        series[arm].append({
            "distance": dist,
            "failure_rate": round(1 - p, 3),
            "ci_lo": round(lo, 3),
            "ci_hi": round(hi, 3),
            "n": n,
        })

    return dict(sorted(series.items()))


def print_table(agg: dict[str, Any]) -> None:
    """Human-readable summary table to stdout."""
    print(f"\n{'='*72}")
    print(f"  SWEEP SUMMARY — {agg['total_episodes']} episodes")
    print(f"{'='*72}\n")

    # Per-arm summary
    print(f"{'Arm':>4}  {'n':>3}  {'gov%':>5}  {'CI95':>13}  {'trunc%':>6}  "
          f"{'esc%':>5}  {'att%':>5}  {'ploss%':>6}  {'calls':>5}  {'tok/ep':>7}")
    print("-" * 72)
    for arm, s in sorted(agg["by_arm"].items()):
        ci = f"[{s['gov_ci95'][0]:.2f},{s['gov_ci95'][1]:.2f}]"
        print(f"{arm:>4}  {s['n']:>3}  {s['gov_rate']:>5.1%}  {ci:>13}  "
              f"{s['truncation_rate']:>5.1%}  {s['esc_accuracy']:>5.1%}  "
              f"{s['attenuation_rate']:>5.1%}  {s['prop_loss_rate']:>5.1%}  "
              f"{s['mean_calls']:>5.0f}  {s['mean_prompt_tokens']:>7.0f}")

    # Headline figure data
    print(f"\n{'─'*72}")
    print("  HEADLINE: governance failure rate by constraint_distance")
    print(f"{'─'*72}")
    for arm, points in sorted(agg["headline"].items()):
        pts = "  ".join(f"d={p['distance']}:{p['failure_rate']:.0%}(n={p['n']})"
                        for p in points)
        print(f"  {arm}: {pts}")

    # Grid
    print(f"\n{'─'*72}")
    print("  GRID: arm × distance")
    print(f"{'─'*72}")
    print(f"  {'cell':>12}  {'n':>3}  {'gov%':>5}  {'att%':>5}  {'ploss%':>6}  violations")
    for cell, s in sorted(agg["grid"].items()):
        viols = ", ".join(f"{k}:{v}" for k, v in s["violations"].items()) or "—"
        print(f"  {cell:>12}  {s['n']:>3}  {s['gov_rate']:>5.1%}  "
              f"{s['attenuation_rate']:>5.1%}  {s['prop_loss_rate']:>5.1%}  {viols}")

    print()
