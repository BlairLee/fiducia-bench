# fiducia-bench

**Benchmarking the *governability* of financial agents.**

Existing agent benchmarks measure *capability* — can the agent finish the task.
Fiducia measures *governability* — can the agent finish the task reliably, within
policy, with an auditable trail, and escalate exactly when it should.

Status: **Phase 1** — deterministic end-to-end pipeline (environment, scripted
simulator, verifiers, metrics) validated on the first `kyc_case` seed tasks.

## Quick start

```bash
pip install -e .
python -m fiducia.cli run --task tasks/seed/kyc-0001.yaml --agent oracle
python -m fiducia.cli run --task tasks/seed/kyc-0002.yaml --agent naive   # falls in the trap
python tests/test_e2e.py
```

## Design in one paragraph

Each task YAML is question + answer key + grading rubric in one file: a simulated
customer (with *hidden info* revealed only under the right questions), an allow-listed
tool set over a seeded mock-bank state, and an `expected` block (terminal state,
required/forbidden actions, escalation ground truth). A machine-readable **policy
pack** declares per-rule deterministic checks (`require_before`, `allow_list`,
`state_assert`). Verification **replays** the trajectory against a fresh environment
so rule triggers are evaluated against the state *as it was* at each tool call — the
audit log is environment-owned and never trusted from the agent. Headline metric:
**governed success** = task success ∧ zero critical violations ∧ correct escalation
behavior (both directions: recall on 0003/0004-style tasks, precision on 0001/0005).

## Layout

```
fiducia/          # library: schema, env (state+tools), simulator, agents, verify, runner, cli
envs/db/          # seed databases (synthetic)
envs/policies/    # machine-readable policy packs
tasks/seed/       # hand-written seed tasks
tests/            # e2e: oracle passes, naive gets caught
```

## Roadmap

- [x] Phase 1: deterministic closed loop (scripted simulator + scripted agents)
- [ ] Phase 2: LLM user simulator (pinned open-weights via local vLLM) + OpenAI-compatible agent harness
- [ ] Seed tasks 0003–0005 (sanctions fuzzy-match, hidden UBO, PEP false-positive mirror)
- [ ] pass^k aggregation + baselines (4–6 models × single-agent vs plan/research/synthesize)

All entities, rules, and jurisdictions are synthetic. Policy rules are *inspired by*
public KYC/AML guidance and are not real regulations. Not legal or compliance advice.

License: Apache-2.0
