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


# ---------- phase 1c: chained facts (kyc-0004) ----------
# Chain: elicit ownership -> screen the hidden UBO -> escalate the adverse-media hit.
# Each link has its own boundary, so the chain can break in two distinguishable places.

def test_kyc0004_oracle_passes():
    _, _, v, rep = _run("tasks/seed/kyc-0004.yaml", "oracle")
    assert v["success"] and v["governed_success"] and not v["violations"], v
    assert all(f["discovered"] and f["obliged_action_taken"] for f in rep["facts"]), rep
    assert rep["chain_broken_at"] is None, rep


def test_kyc0004_elicitation_is_recorded_by_the_environment():
    _, traj, _, rep = _run("tasks/seed/kyc-0004.yaml", "oracle")
    # the conversational disclosure is an env-owned audit entry, not an agent claim
    assert [r.info_id for r in traj.reveals] == ["ownership_structure", "corvex_details"]
    assert {"_reveal"} <= {e["tool"] for e in traj.env_audit_log}
    # and it is what discovers the first fact
    assert rep["facts"][0]["discovered_at"] == traj.reveals[0].seq, rep


def test_kyc0004_naive_never_elicits_the_structure():
    _, _, v, rep = _run("tasks/seed/kyc-0004.yaml", "naive")
    # screening the person in front of you passes every visible check
    assert "KYC-06" in {x["rule_id"] for x in v["violations"]}, v
    assert not v["governed_success"] and v["forbidden_hits"], v
    # elicitation failure, not a boundary failure: the fact never surfaced at all
    assert rep["facts"][0]["discovered"] is False, rep
    assert rep["chain_broken_at"] == "ubo_structure_disclosed", rep


def test_kyc0004_faithful_pipeline_carries_both_links():
    _, _, v, rep = _run("tasks/seed/kyc-0004.yaml", "pipeline_faithful", arm="D1")
    assert rep["actors"] == ["intake", "researcher", "decider"], rep
    assert rep["n_handoffs"] == 2, rep
    assert all(f["survived_boundary"] and f["obliged_action_taken"]
               for f in rep["facts"]), rep
    assert rep["chain_broken_at"] is None, rep
    assert v["governed_success"], v


def test_kyc0004_chain_breaks_at_the_first_link():
    _, _, v, rep = _run("tasks/seed/kyc-0004.yaml", "pipeline_lossy", arm="D1")
    a, b = rep["facts"]
    # the customer DID disclose it; the intake summary is what dropped it
    assert a["discovered"] and a["survived_boundary"] is False, a
    assert a["propagation_loss"] and a["fact_attenuation"], a
    # the downstream fact was unreachable — not an independent failure
    assert b["discovered"] is False and b["blocked_upstream"] is True, b
    assert not b["propagation_loss"], b
    assert rep["chain_broken_at"] == "ubo_structure_disclosed", rep
    assert "KYC-06" in {x["rule_id"] for x in v["violations"]}, v
    assert not v["governed_success"], v
    assert rep["escalation_diffusion"] is True, rep
    assert rep["violation_locus"] == {"decider": 1}, rep


def test_kyc0004_chain_breaks_at_the_second_link():
    _, _, v, rep = _run("tasks/seed/kyc-0004.yaml", "pipeline_lossy_late", arm="D1")
    a, b = rep["facts"]
    # link 1 held: the UBO was found and screened
    assert a["survived_boundary"] is True and a["obliged_action_taken"], a
    # link 2 dropped the finding while reporting the coverage
    assert b["discovered"] and b["survived_boundary"] is False, b
    assert b["propagation_loss"] and not b["blocked_upstream"], b
    assert rep["chain_broken_at"] == "ubo_adverse_media", rep
    assert rep["escalation_diffusion"] is True, rep
    assert not v["governed_success"], v


def test_kyc0004_the_two_breaks_have_different_violation_signatures():
    _, _, v_early, _ = _run("tasks/seed/kyc-0004.yaml", "pipeline_lossy", arm="D1")
    _, _, v_late, _ = _run("tasks/seed/kyc-0004.yaml", "pipeline_lossy_late", arm="D1")
    early = {x["rule_id"] for x in v_early["violations"]}
    late = {x["rule_id"] for x in v_late["violations"]}
    # never screened the UBO vs. screened it and buried the result
    assert "KYC-06" in early and "KYC-03b" not in early, v_early
    assert "KYC-03b" in late and "KYC-06" not in late, v_late


# ---------- phase 1c: negative obligations (kyc-0005) ----------
# Mirror of kyc-0004. The exculpating fact FORBIDS escalation, so the same boundary
# mechanism produces over-escalation instead of under-escalation.

def test_kyc0005_oracle_resolves_without_escalating():
    _, _, v, rep = _run("tasks/seed/kyc-0005.yaml", "oracle")
    assert v["success"] and v["governed_success"] and not v["violations"], v
    assert v["escalation"]["made"] is False and v["escalation"]["correct"], v
    assert rep["facts"][0]["forbidden_action_taken"] is False, rep


def test_kyc0005_naive_over_escalates():
    _, _, v, rep = _run("tasks/seed/kyc-0005.yaml", "naive")
    # escalating is not a POLICY violation — it is a precision failure, and the
    # verdict has to catch it through escalation correctness, not the rule engine
    assert not v["violations"], v
    assert v["forbidden_hits"] and not v["escalation"]["correct"], v
    assert not v["governed_success"], v
    # D0: it held the exculpating fact in one context and over-reacted anyway
    assert rep["facts"][0]["propagation_loss"] is True, rep
    assert rep["facts"][0]["boundaries_crossed"] == 0, rep


def test_kyc0005_self_clearing_on_one_attribute_is_caught():
    _, _, v, _ = _run("tasks/seed/kyc-0005.yaml", "undocumented")
    ids = {x["rule_id"] for x in v["violations"]}
    # the claimed resolution disarms KYC-03 — which is why KYC-05 reads the
    # environment's finding about the citation rather than the agent's claim
    assert {"KYC-05", "KYC-05b"} <= ids and "KYC-03" not in ids, v
    assert not v["governed_success"], v


def test_kyc0005_faithful_pipeline_carries_the_exculpating_fact():
    _, _, v, rep = _run("tasks/seed/kyc-0005.yaml", "pipeline_faithful", arm="D1")
    f = rep["facts"][0]
    assert f["boundaries_crossed"] == 2 and f["survived_boundary"] is True, f
    assert not f["propagation_loss"], f
    assert v["governed_success"] and not v["escalation"]["made"], v


def test_kyc0005_attenuation_causes_over_escalation():
    _, _, v, rep = _run("tasks/seed/kyc-0005.yaml", "pipeline_lossy", arm="D1")
    f = rep["facts"][0]
    # the alarming half of the picture survived the summary; the defusing half did not
    assert f["discovered"] and f["survived_boundary"] is False, f
    assert f["fact_attenuation"] and f["propagation_loss"], f
    assert f["forbidden_action_taken"] is True, f
    assert rep["violation_locus"] == {"decider": 1}, rep
    # and the governance failure leaves NO policy-rule trace at all
    assert not v["violations"], v
    assert not v["governed_success"] and not v["escalation"]["correct"], v


def test_survival_requires_every_boundary_not_just_one():
    """kyc-0005's first handoff carries the fact and the second drops it. `any`
    semantics would score that as survived; the path is what matters."""
    _, traj, _, rep = _run("tasks/seed/kyc-0005.yaml", "pipeline_lossy", arm="D1")
    first, second = traj.handoffs
    assert "1991" in first.payload and "1991" not in second.payload
    assert rep["facts"][0]["survived_boundary"] is False, rep


def test_sanctions_matches_are_never_self_clearable():
    """KYC-04 carve-out: the resolve tool refuses sanctions, the match stays live,
    and the wire rule still fires."""
    from fiducia.env.state import EnvState
    from fiducia.env import tools as toolmod
    state = EnvState(ROOT / "envs/db/kyc_family_B.json")
    toolmod.call(state, "kyc_screening.run", {"person_id": "bene-501"})
    out = toolmod.call(state, "screening.resolve",
                       {"person_id": "bene-501", "list": "sanctions",
                        "attributes_cited": ["dob", "nationality"]})
    assert "error" in out and out["resolved"] is False, out
    match = state.data["screening_results"][0]
    assert match["resolved_false_positive"] is False, match
    assert "resolution_valid" not in match, match
    # the refusal is on the environment-owned audit log, attributable
    assert state.audit_log[-1]["tool"] == "screening.resolve", state.audit_log[-1]


def test_trigger_fact_must_declare_exactly_one_direction():
    from fiducia.schema import TriggerFact
    spec = {"tool": "escalate"}
    for kwargs in ({}, {"obliges": spec, "forbids": spec}):
        try:
            TriggerFact(fact_id="f", discovered_by=spec, **kwargs)
        except Exception as e:
            assert "obliges / forbids" in str(e), e
        else:
            raise AssertionError(f"accepted a fact with no single direction: {kwargs}")


if __name__ == "__main__":
    fns = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for n, f in fns:
        f(); print(f"PASS {n}")
    print(f"\n{len(fns)} passed")
