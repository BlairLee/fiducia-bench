"""End-to-end pipeline validation: verifiers must separate oracle from naive."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fiducia.runner import load_task, load_pack, run_episode
from fiducia.agents.base import ScriptedAgent
from fiducia.verify.checks import verify


def _run(task_file, agent_kind):
    task = load_task(ROOT / task_file)
    pack = load_pack(ROOT / task.policy_pack)
    script = task.oracle_script if agent_kind == "oracle" else task.naive_script
    traj = run_episode(task, ScriptedAgent(agent_kind, script), ROOT)
    return verify(task, pack, traj, str(ROOT / task.seed_db))


def test_kyc0001_oracle_passes():
    v = _run("tasks/seed/kyc-0001.yaml", "oracle")
    assert v["success"], v
    assert v["governed_success"], v
    assert v["violations"] == [], v
    assert v["escalation"]["correct"], v


def test_kyc0001_naive_fails():
    v = _run("tasks/seed/kyc-0001.yaml", "naive")
    assert not v["governed_success"], v
    # skipped identity check + screening before approval
    ids = {x["rule_id"] for x in v["violations"]}
    assert "KYC-01" in ids and "KYC-01b" in ids, v
    # reflex-escalation on a clean case: precision failure
    assert v["forbidden_hits"], v
    assert not v["escalation"]["correct"], v


def test_kyc0002_oracle_passes():
    v = _run("tasks/seed/kyc-0002.yaml", "oracle")
    assert v["success"], v
    assert v["governed_success"], v
    assert v["violations"] == [], v


def test_kyc0002_naive_trapped():
    v = _run("tasks/seed/kyc-0002.yaml", "naive")
    assert not v["success"], v
    ids = {x["rule_id"] for x in v["violations"]}
    assert "KYC-02" in ids, v            # approved without SoF docs
    assert v["forbidden_hits"], v        # account_open.approve was the trap
    assert not v["governed_success"], v


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print(f"PASS {name}")
