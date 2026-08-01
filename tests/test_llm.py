"""LLM brain: prompt assembly, schema generation, parsing, and full episodes.

Every test here is hermetic — `ReplayTransport` returns canned responses and no socket
is opened. That is deliberate: the harness has to be verifiable without an endpoint, a
GPU, or a budget, or nobody can reproduce the benchmark.
"""
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fiducia.agents.llm import (LLMBrain, LLMClient, ReplayTransport, build_arm,
                                parse_response, tools_for)
from fiducia.agents.llm import prompts
from fiducia.agents.llm.build import D1_STAGES
from fiducia.agents.llm.schema import (DELEGATE, FINISH, HANDOFF, from_wire, to_wire)
from fiducia.runner import load_task, load_pack, run_episode
from fiducia.verify.checks import verify
from fiducia.verify.decomposition import decomposition_report

TASK = "tasks/seed/kyc-0003.yaml"


def _task():
    task = load_task(ROOT / TASK)
    return task, load_pack(ROOT / task.policy_pack)


def _say(text):
    return {"choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 10}}


def _call(name, arguments="{}", call_id="c1"):
    return {"choices": [{"message": {"content": "", "tool_calls": [
        {"id": call_id, "type": "function",
         "function": {"name": name, "arguments": arguments}}]},
        "finish_reason": "tool_calls"}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 20}}


def _client(responses):
    return LLMClient("http://localhost:8000/v1", "test-model",
                     transport=ReplayTransport(list(responses)))


# ---------- parsing ----------

def test_tool_call_becomes_a_tool_action():
    action, err = parse_response(_call("escalate", '{"target": "sanctions_team"}'))
    assert err is None and action == {"tool": "escalate",
                                      "args": {"target": "sanctions_team"}}, action


def test_wire_names_obey_the_openai_function_grammar():
    """Dots are not legal in a function name; the model should never see one."""
    import re
    for s in tools_for(["customer_db.read", "transactions.wire_execute"]):
        name = s["function"]["name"]
        assert re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", name), name
    assert to_wire("customer_db.read") == "customer_db__read"
    assert from_wire("customer_db__read") == "customer_db.read"
    assert from_wire(FINISH) == FINISH          # control names pass through


def test_wire_names_are_mapped_back_before_the_tool_is_called():
    action, err = parse_response(_call("transactions__wire_execute", '{"amount": 1}'))
    assert err is None and action["tool"] == "transactions.wire_execute", action


def test_control_tools_map_to_protocol_actions():
    assert parse_response(_call(FINISH))[0] == {"done": True}
    assert parse_response(_call(HANDOFF, '{"summary": "s"}'))[0] == {
        "handoff_payload": "s"}
    assert parse_response(_call(DELEGATE, '{"agent": "researcher", "brief": "b"}'))[0] \
        == {"delegate": "researcher", "brief": "b"}


def test_plain_content_becomes_a_message():
    assert parse_response(_say("Who is the beneficiary?"))[0] == {
        "message": "Who is the beneficiary?"}


def test_malformed_output_is_an_error_not_an_action():
    for bad in (_call("escalate", "{not json"), _call(""), _say(""),
                {"choices": []}):
        action, err = parse_response(bad)
        assert action is None and err, (bad, action, err)


def test_parse_failures_are_recorded_and_repaired():
    brain = LLMBrain("agent", _client([_call("escalate", "{oops"),
                                       _call("escalate", '{"target": "edd_team"}')]),
                     "sys", tools_for(["escalate"]))
    action = brain.step({})
    assert action == {"tool": "escalate", "args": {"target": "edd_team"}}, action
    assert brain.parse_failures == 1, brain.call_log
    assert [c.parse_error is None for c in brain.call_log] == [False, True]


def test_a_brain_that_never_parses_stops_rather_than_guessing():
    brain = LLMBrain("agent", _client([_call("x", "{bad")] * 2), "sys", max_repairs=1)
    assert brain.step({}) == {"done": True}
    assert brain.parse_failures == 2, brain.call_log


# ---------- tool schemas ----------

def test_schemas_are_generated_from_the_environment_registry():
    schemas = tools_for(["kyc_screening.run", "escalate"])
    by_name = {s["function"]["name"]: s for s in schemas}
    assert "kyc_screening__run" in by_name and FINISH in by_name
    params = by_name["escalate"]["function"]["parameters"]
    assert params["properties"]["target"]["type"] == "string"
    assert params["required"] == ["target"]


def test_unimplemented_tools_are_not_offered():
    assert not [s for s in tools_for(["not_a_real_tool"])
                if s["function"]["name"] == "not_a_real_tool"]


def test_control_tools_follow_the_topology():
    names = lambda **kw: {s["function"]["name"] for s in tools_for([], **kw)}
    assert names() == {FINISH}
    assert names(can_handoff=True) == {FINISH, HANDOFF}
    assert names(delegates=["researcher"]) == {FINISH, DELEGATE}


# ---------- factor P ----------

def test_p0_puts_the_policy_in_context_and_p1_does_not():
    task, pack = _task()
    p0, p1 = prompts.d0_prompt(task, pack, "P0"), prompts.d0_prompt(task, pack, "P1")
    assert "KYC-04" in p0 and "sanctions" in p0.lower(), p0
    assert "KYC-04" not in p1 and "policy_lookup.search" in p1, p1
    # the ONLY difference is the policy block: role and conduct are shared verbatim
    assert prompts.ROLE in p0 and prompts.ROLE in p1
    assert prompts.CONDUCT in p0 and prompts.CONDUCT in p1


def test_p1_can_retrieve_exactly_what_p0_was_given():
    """Otherwise the factor confounds access mode with policy content."""
    task, pack = _task()
    traj = run_episode(task, _StubAgent(), ROOT)
    corpus = {r["rule_id"] for r in traj.final_state["_policy_texts"]}
    assert corpus == {r.rule_id for r in pack.rules}, corpus


class _StubAgent:
    name = "stub"

    def step(self, observation):
        return {"done": True}


def test_arm_prompts_differ_only_in_the_topology_paragraph():
    task, pack = _task()
    stages = list(D1_STAGES)
    d0 = prompts.d0_prompt(task, pack)
    d1 = prompts.d1_prompt(task, pack, stages, 0)
    for shared in (prompts.ROLE, prompts.CONDUCT, prompts.policy_text(pack),
                   prompts.case_block(task)):
        assert shared in d0 and shared in d1
    assert "by yourself" in d0 and "by yourself" not in d1


def test_every_component_is_told_whose_case_it_is():
    """A real model has no idea otherwise — the fixture scripts hardcoded the id."""
    task, pack = _task()
    for p in (prompts.d0_prompt(task, pack),
              prompts.d1_prompt(task, pack, list(D1_STAGES), 2),
              prompts.d2_subagent_prompt(task, pack, "researcher", ["customer_db.read"])):
        assert task.subject in p, p
    # but never the parties that have to be elicited or looked up
    assert "bene-501" not in prompts.d0_prompt(task, pack)


# ---------- full episodes ----------

def test_an_episode_that_runs_out_of_steps_is_marked_truncated():
    """Otherwise "chose not to escalate" and "never got there" score the same."""
    task, pack = _task()
    chatty = _client([_say("Could you confirm the beneficiary?")] * 4)
    traj = run_episode(task, build_arm(task, pack, "D0", chatty), ROOT, max_steps=4)
    assert traj.truncated is True, traj.truncated

    finishing = _client([_say("One moment."), _call(FINISH)])
    traj = run_episode(task, build_arm(task, pack, "D0", finishing), ROOT, max_steps=4)
    assert traj.truncated is False, traj.truncated


def test_d0_episode_end_to_end_with_a_canned_model():
    task, pack = _task()
    client = _client([
        _say("Who is the beneficiary on this wire?"),
        _call("kyc_screening__run", '{"person_id": "bene-501"}'),
        _call("transactions__freeze", '{"reason": "screening match"}'),
        _call("escalate", '{"target": "sanctions_team", "reason": "sanctions match"}'),
        _say("The wire is on hold pending review."),
        _call(FINISH),
    ])
    arm = build_arm(task, pack, "D0", client)
    traj = run_episode(task, arm, ROOT)
    v = verify(task, pack, traj, str(ROOT / task.seed_db))
    assert v["governed_success"], v
    assert traj.arm == "D0" and traj.model_fingerprint["policy_mode"] == "P0"
    assert len(traj.llm_calls) == 6 and not any(c.parse_error for c in traj.llm_calls)
    assert traj.llm_calls[0].prompt_tokens == 100


def test_d1_episode_records_the_handoff_the_model_wrote():
    task, pack = _task()
    summary = "Beneficiary bene-501: screening returned a sanctions match, fuzzy."
    client = _client([
        _say("Who is the beneficiary on this wire?"),
        _call(HANDOFF, '{"summary": %s}' % json.dumps(summary)),
        _call("kyc_screening__run", '{"person_id": "bene-501"}'),
        _call(HANDOFF, '{"summary": %s}' % json.dumps(summary)),
        _call("transactions__freeze", '{"reason": "screening match"}'),
        _call("escalate", '{"target": "sanctions_team", "reason": "sanctions match"}'),
        _call(FINISH),
    ])
    arm = build_arm(task, pack, "D1", client)
    traj = run_episode(task, arm, ROOT)
    v = verify(task, pack, traj, str(ROOT / task.seed_db))
    rep = decomposition_report(task, traj, v)
    assert traj.arm == "D1" and rep["actors"] == ["research", "decide"], rep
    assert [h.payload for h in traj.handoffs] == [summary, summary]
    assert rep["facts"][0]["survived_boundary"] is True, rep
    assert v["governed_success"], v


def test_d1_lossy_handoff_reproduces_the_failure_with_a_real_model_loop():
    task, pack = _task()
    client = _client([
        _say("Who is the beneficiary on this wire?"),
        _call(HANDOFF, '{"summary": "Customer wants a same-day wire."}'),
        _call("kyc_screening__run", '{"person_id": "bene-501"}'),
        _call(HANDOFF, '{"summary": "Beneficiary checks complete, nothing outstanding."}'),
        _call("transactions__wire_execute",
              '{"amount": 12000, "beneficiary": "bene-501"}'),
        _call(FINISH),
    ])
    traj = run_episode(task, build_arm(task, pack, "D1", client), ROOT)
    v = verify(task, pack, traj, str(ROOT / task.seed_db))
    rep = decomposition_report(task, traj, v)
    assert rep["facts"][0]["fact_attenuation"], rep
    assert "KYC-04" in {x["rule_id"] for x in v["violations"]}, v
    assert rep["violation_locus"] == {"decide": 1}, rep


def test_d2_subagent_refusal_is_reported_back_to_the_model():
    task, pack = _task()
    client = _client([
        _call(DELEGATE, '{"agent": "researcher", "brief": "Screen bene-501."}'),
        _call("kyc_screening__run", '{"person_id": "bene-501"}'),
        _call("escalate", '{"target": "sanctions_team"}'),          # out of scope
        _call(HANDOFF, '{"summary": "bene-501 has a fuzzy sanctions match."}'),
        _call("transactions__freeze", '{"reason": "screening match"}'),
        _call("escalate", '{"target": "sanctions_team", "reason": "sanctions match"}'),
        _call(FINISH),
    ])
    arm = build_arm(task, pack, "D2", client)
    traj = run_episode(task, arm, ROOT)
    v = verify(task, pack, traj, str(ROOT / task.seed_db))
    assert [b.tool for b in traj.blocked_calls] == ["escalate"], traj.blocked_calls
    # the refusal reached the subagent's conversation, keeping it well-formed
    sub_messages = arm.subagents["researcher"][0].messages
    assert any(m["role"] == "tool" and "refused" in m["content"] for m in sub_messages)
    assert v["governed_success"], v


def test_the_model_never_gets_upstream_context_it_should_not_have():
    """The isolation guarantee, checked on the actual prompts sent to the endpoint."""
    task, pack = _task()
    transport = ReplayTransport([
        _say("Who is the beneficiary?"),
        _call(HANDOFF, '{"summary": "beneficiary is bene-501"}'),
        _call("kyc_screening__run", '{"person_id": "bene-501"}'),
        _call(HANDOFF, '{"summary": "screening done"}'),
        _call(FINISH),
    ])
    client = LLMClient("http://x/v1", "test-model", transport=transport)
    run_episode(task, build_arm(task, pack, "D1", client), ROOT)
    final_stage_request = transport.requests[-1]
    blob = str(final_stage_request["messages"])
    assert "screening done" in blob                 # its inbox, yes
    assert "transliteration variant" not in blob    # the upstream tool result, no
    assert "Kovalenko" not in blob                  # the upstream conversation, no


if __name__ == "__main__":
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    for n, f in fns:
        f(); print(f"PASS {n}")
    print(f"\n{len(fns)} passed")
