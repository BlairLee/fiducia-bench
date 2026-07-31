# CLAUDE.md — fiducia-bench

Context for Claude Code sessions on this repo. Read this before proposing changes.

## What this is

An open-source benchmark + paper on the **governability** of financial agents. Existing
agent benchmarks measure *capability* (did the agent finish the task). This one measures
whether the agent finished it **within policy, with correct escalation, and an auditable
trail** — and specifically whether **decomposing** an agent degrades that.

**Research question:** *Does decomposing an agent degrade its governability?*
**Mechanism hypothesis:** governance obligations fail at **boundaries** — the trigger fact
is discovered by one component and the obligated action belongs to another; summarization
at the handoff drops the fact.

Target: NeurIPS 2026 workshop short paper first (abstract/full deadlines in Aug–Sep), then
a full paper (ARR or a D&B track). Working title: *Governance at the Boundary.*

## Hard boundary — read this before writing anything

The author works on enterprise agent systems professionally. This repo must stay clean:

- **Everything here is synthetic.** Entities, customers, jurisdictions, and policy rules are
  invented. Rules are *inspired by* public KYC/AML guidance; they are not real regulations
  and nothing here is legal or compliance advice.
- **Never add tasks involving people search, relationship-graph reasoning, warm-intro paths,
  or professional-network navigation.** That is the author's day job and must not appear.
- Architecture patterns under study (ReAct loops, orchestrator/subagent delegation,
  skill-based policy access) are public, generic, and documented in the literature — that is
  why they are studyable here. Do not import specific orchestration internals, prompts,
  routing logic, or performance numbers from any employer system.

## Current status

Phase 1b complete. `python tests/test_e2e.py` → 10 passing.

- Environment: seeded JSON state + deterministic tools, **environment-owned audit log**
- Simulator: scripted, trigger-substring driven (LLM simulator is Phase 2)
- Verifiers: deterministic policy checks via **trajectory replay**
- Decomposition metrics: actor attribution, handoff logging, fact attenuation
- Tasks: kyc-0001 (clean/precision control), kyc-0002 (SoF hidden info), kyc-0003
  (fuzzy sanctions match, with `pipeline_faithful` vs `pipeline_lossy` variants)

## Non-negotiable design invariants

Break these and the benchmark stops being credible:

1. **The environment owns the audit log and actor attribution.** Never let an agent write
   its own audit entry or declare its own actor. `EnvState.log(..., actor=)` is the only path.
2. **Verification replays the trajectory** against a fresh environment so rule triggers are
   evaluated against state *as it was* at each tool call — not the final state. See
   `verify/checks.py::_replay_states`.
3. **Prefer deterministic checks.** Target ≥70% of policy rules checkable without a judge
   (`require_before`, `allow_list`, `state_assert`). Judges are for genuinely soft rules only,
   and must be calibrated against human labels.
4. **Every metric is a pure function of (trajectory + task YAML).** This lets historical runs
   be re-scored when verifiers improve. Don't compute metrics during rollout.
5. **Every task carries an oracle script and a trap script.** They are that task's unit test:
   the verifiers must separate them. A task without both is not done.
6. **Traps are the point.** Hard tasks contain a path that satisfies the user's surface goal
   while violating policy. Escalation is scored in *both* directions — over-escalating a clean
   case is a failure too (see kyc-0001, and 0005 when built).

## Layout

```
fiducia/
  schema.py              Task, PolicyPack, TriggerFact, Handoff, Trajectory (pydantic)
  env/state.py           EnvState + environment-owned audit log
  env/tools.py           deterministic tools, @tool registry
  simulator/scripted.py  Phase-1 user simulator
  agents/base.py         ScriptedAgent; OpenAICompatAgent stub for Phase 2
  verify/checks.py       policy rules + task expectations -> verdict
  verify/decomposition.py  propagation loss, fact attenuation, violation locus, diffusion
  runner.py              episode loop; actor + handoff recording
  cli.py                 python -m fiducia.cli run --task ... --script ... --arm ...
envs/db/                 seed databases (synthetic)
envs/policies/           machine-readable policy packs
tasks/seed/              hand-written seed tasks
docs/                    schema design, seed-task designs, novelty sweep, experiment design
```

## Experiment design (summary; full version in docs/)

Two orthogonal factors:

- **D — decomposition:** `D0` single ReAct loop · `D1` fixed pipeline (plan→research→decide)
  · `D2` dynamic subagents with narrowed tool scopes
- **P — policy access:** `P0` full policy in context · `P1` retrieval-on-demand via
  `policy_lookup` (models the skill-based pattern)

Core grid: D0×P0, D0×P1, D1×P0, D2×P0. `D0×P1 vs D0×P0` isolates policy visibility without
decomposition — if P1 alone explains the degradation, the paper is retitled around policy
access, not decomposition.

Headline figure: **governance failure rate vs. `constraint_distance`, one line per arm.**
`constraint_distance` = number of component boundaries the trigger fact must cross between
discovery and obligated action.

## What's next (in order)

1. **kyc-0004** — business account, hidden UBO. Two *chained* trigger facts (elicit ownership
   → screen the hidden UBO). Will stress whether the registry handles fact chains.
2. **kyc-0005** — PEP exact-name match that is a *resolvable false positive*. The obligation is
   **negative**: must NOT escalate, and must document a two-attribute mismatch before
   approving. `TriggerFact.obliges` cannot express this today — likely needs `forbids` or
   `obliges_absence`. Mirror-image of 0004; together they prevent gaming escalation by
   always escalating.
3. Arm harness: real D0/D1/D2 implementations over the shared tool layer (scripted versions
   first, to unit-test attribution).
4. LLM user simulator against a local OpenAI-compatible endpoint; pin model + quantization +
   sampling params for reproducibility.
5. Pilot: 20 tasks × 4 arms × 2 models × k=2 → measure per-episode cost before the full grid.
6. Template expansion to ~100 instances, weighted toward `constraint_distance >= 2`.

## Conventions

- Python ≥3.11, pydantic v2, PyYAML. No heavy deps without a reason.
- Tasks are YAML; scripts live under `scripts:` keyed by name (`oracle`, `naive`,
  `pipeline_faithful`, `pipeline_lossy`).
- Run tests with `python tests/test_e2e.py` (plain asserts, pytest-compatible).
- When adding a policy rule, add the task that exercises it *and* the trap script that
  violates it in the same change.

## Prior art to position against (details in docs/fiducia-novelty-sweep-2026-07.md)

The field moved fast in 2026. Already taken: capability-vs-governed gap ("corrupt success",
arXiv 2603.03116), paired should-act/should-abstain design (AgentAbstain, 2607.10059),
hidden-policy-fact violations (PhantomPolicy, 2604.12177), escalation calibration
(2604.08588). τ³-bench now has a banking domain. What survives here: **obligation-based**
escalation (correctness fixed by a rule hierarchy, not model confidence), policy packs as
portable machine-checkable artifacts, audit reconstructability as a scored metric, and the
decomposition question. Position honestly — this is an integration + domain-depth
contribution, not a first-mover one.
