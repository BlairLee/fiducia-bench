# fiducia-bench

**Benchmarking the *governability* of financial agents.**

Existing agent benchmarks measure *capability* — can the agent finish the task.
Fiducia measures *governability* — can the agent finish the task reliably, within
policy, with an auditable trail, and escalate exactly when it should.

**Research question:** *Does decomposing an agent degrade its governability?*
Governance obligations fail at **boundaries** — between components, between what one
component discovered and what another decides. Fiducia is the instrument that isolates it.

Status: **Phase 1b** — deterministic pipeline plus decomposition metrics (actor
attribution, handoff logging, fact attenuation) validated on `kyc_case` seed tasks.

## Quick start

```bash
pip install -e .
python -m fiducia.cli run --task tasks/seed/kyc-0001.yaml --script oracle
python -m fiducia.cli run --task tasks/seed/kyc-0002.yaml --script naive          # falls in the trap
python -m fiducia.cli run --task tasks/seed/kyc-0003.yaml --script pipeline_lossy --arm D1
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

## Decomposition metrics

`kyc-0003` ships two scripts with the **same** researcher→decider architecture. In
`pipeline_faithful` the screening result reaches the decider and the wire is frozen. In
`pipeline_lossy` the researcher's summary omits it — the decider then executes the wire.
Same architecture, same discovery; only the handoff payload differs. The harness reports:

- **fact attenuation** — did the trigger fact survive the boundary (checked against the
  logged handoff payload, not the agent's claim)
- **propagation loss** — fact discovered, obliged action never taken
- **violation locus** — which component issued the violating call
- **escalation diffusion** — obligation dropped at a boundary vs. actively decided against

`constraint_distance` on each task records how many boundaries the trigger fact must
cross; the headline figure is governance failure rate vs. constraint distance, per arm.

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
- [x] Phase 1b: actor attribution, handoff logging, trigger-fact registry, decomposition metrics
- [x] kyc-0003 (fuzzy sanctions match) with faithful vs lossy pipeline variants
- [ ] Seed tasks 0004–0005 (hidden UBO, PEP false-positive mirror)
- [ ] Arm harness: D0 single ReAct loop / D1 fixed pipeline / D2 dynamic subagents,
      crossed with P0 in-context policy / P1 retrieval-on-demand
- [ ] pass^k aggregation + pilot cost model + baselines across ≥3 models

All entities, rules, and jurisdictions are synthetic. Policy rules are *inspired by*
public KYC/AML guidance and are not real regulations. Not legal or compliance advice.

License: Apache-2.0
