"""End-to-end validation.

Phase 1: verifiers separate oracle from naive (capability vs governance).
Phase 1b: decomposition metrics separate a FAITHFUL pipeline from a LOSSY one that
runs the same architecture but drops the trigger fact at the boundary.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fiducia.runner import load_task, load_pack, run_episode
from fiducia.agents.base import ScriptedAgent
from fiducia.verify.checks import verify
from fiducia.verify.decomposition import decomposition_report


def _run(task_file, script_name, arm="D0"):
    task = load_task(ROOT / task_file)
    pack = load_pack(ROOT / task.policy_pack)
    agent = ScriptedAgent(script_name, task.scripts[script_name])
    traj = run_episode(task, agent, ROOT, arm=arm)
    verdict = verify(task, pack, traj, str(ROOT / task.seed_db))
    return task, traj, verdict, decomposition_report(task, traj, verdict)


# ---------- phase 1: governance verifiers ----------

def test_kyc0001_oracle_passes():
    _, _, v, _ = _run("tasks/seed/kyc-0001.yaml", "oracle")
    assert v["success"] and v["governed_success"] and not v["violations"], v


def test_kyc0001_naive_fails():
    _, _, v, _ = _run("tasks/seed/kyc-0001.yaml", "naive")
    ids = {x["rule_id"] for x in v["violations"]}
    assert {"KYC-01", "KYC-01b"} <= ids, v
    assert v["forbidden_hits"] and not v["escalation"]["correct"], v


def test_kyc0002_oracle_passes():
    _, _, v, _ = _run("tasks/seed/kyc-0002.yaml", "oracle")
    assert v["success"] and v["governed_success"] and not v["violations"], v


def test_kyc0002_naive_trapped():
    _, _, v, _ = _run("tasks/seed/kyc-0002.yaml", "naive")
    assert "KYC-02" in {x["rule_id"] for x in v["violations"]}, v
    assert not v["governed_success"], v


def test_kyc0003_oracle_passes():
    _, _, v, _ = _run("tasks/seed/kyc-0003.yaml", "oracle")
    assert v["governed_success"], v
    assert v["escalation"]["correct"], v


def test_kyc0003_naive_violates_sanctions_rule():
    _, _, v, _ = _run("tasks/seed/kyc-0003.yaml", "naive")
    assert "KYC-04" in {x["rule_id"] for x in v["violations"]}, v
    assert not v["governed_success"], v


# ---------- phase 1b: decomposition metrics ----------

def test_attribution_is_recorded():
    _, traj, _, rep = _run("tasks/seed/kyc-0003.yaml", "pipeline_faithful", arm="D1")
    assert rep["actors"] == ["researcher", "decider"], rep
    assert rep["n_handoffs"] == 1, rep
    # environment-owned audit log carries the actor, not the agent's claim
    actors_logged = {e["actor"] for e in traj.env_audit_log}
    assert {"researcher", "decider"} <= actors_logged, actors_logged


def test_faithful_pipeline_preserves_the_fact():
    _, _, v, rep = _run("tasks/seed/kyc-0003.yaml", "pipeline_faithful", arm="D1")
    f = rep["facts"][0]
    assert f["discovered"] and f["survived_boundary"] is True, f
    assert not f["propagation_loss"] and not f["fact_attenuation"], f
    assert v["governed_success"], v


def test_lossy_pipeline_loses_the_fact_at_the_boundary():
    _, _, v, rep = _run("tasks/seed/kyc-0003.yaml", "pipeline_lossy", arm="D1")
    f = rep["facts"][0]
    # same architecture, same discovery — the summary is what fails
    assert f["discovered"], f
    assert f["survived_boundary"] is False, f
    assert f["fact_attenuation"] and f["propagation_loss"], f
    assert not v["governed_success"], v
    # the obligation was dropped, not decided against
    assert rep["escalation_diffusion"] is True, rep
    # and the violation is attributed to the deciding component
    assert rep["violation_locus"] == {"decider": 1}, rep


def test_d0_has_no_boundary_to_lose_the_fact_at():
    _, _, _, rep = _run("tasks/seed/kyc-0003.yaml", "oracle")
    assert rep["n_handoffs"] == 0, rep
    assert rep["facts"][0]["survived_boundary"] is None, rep


if __name__ == "__main__":
    fns = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for n, f in fns:
        f(); print(f"PASS {n}")
    print(f"\n{len(fns)} passed")
