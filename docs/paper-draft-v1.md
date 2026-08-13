# Governance at the Boundary: How Agent Decomposition Degrades Policy Compliance

## Abstract

Agent benchmarks measure whether the agent finished the task. We measure whether it
finished it *within policy*. We introduce Fiducia-bench, a benchmark for the
*governability* of financial agents — whether they escalate when obligated, abstain when
required, and leave an auditable trail — and use it to study a question no existing
benchmark answers: **does decomposing an agent into components degrade its governance?**

We find that it does, and the mechanism is specific: policy-relevant facts discovered
by one component are *attenuated at the handoff boundary* before reaching the component
that must act on them. No component decides wrongly — the researcher screens
diligently, the decider acts reasonably on what it received — yet the obligation is
lost. In a 300-episode experiment over 100 KYC/AML task variants and three
architectures, the single-loop baseline attenuated 0% of discovered facts at constraint
distance 2. The fixed pipeline attenuated 56%. The orchestrator-subagent architecture
attenuated 85%. The same mechanism produces both under-escalation (a risk fact is
dropped) and over-escalation (an exculpating fact is dropped).

The benchmark, all tasks, policy packs, and the verification harness are open-source.

---

## 1. Introduction

Enterprise agent systems are moving from single reasoning loops to
orchestrator-subagent architectures. The motivation is engineering: modularity, tool
scoping, specialization, and the hope that smaller components are easier to test and
constrain than monolithic ones. What has not been asked is whether this decomposition
degrades the agent's ability to comply with the rules that govern its work.

The question is not academic. In regulated industries — banking, insurance, healthcare
— an agent that completes a task correctly but violates a procedural rule has failed in
a way no capability benchmark can see. A customer's wire transfer executes, but the
sanctions screening that should have blocked it was conducted on the wrong party. An
account opens, but the ownership structure that should have triggered enhanced due
diligence was elicited by one component and summarized away before reaching the one
that decides. The task succeeds. The governance fails. And the failure is invisible
unless the evaluator checks the procedure, not just the outcome.

Existing work has begun to measure this gap. Corrupt Success [1] re-scores capability
benchmarks with procedure-awareness. AgentAbstain [2] pairs should-act and
should-abstain tasks so the agent cannot game the metric by always acting. PhantomPolicy
[3] hides policy facts from the agent's context to test whether it seeks them out.
Act-or-Escalate [4] measures escalation calibration. But none of these varies the
*architecture* while holding the task and model constant. They give per-model failure
signatures — we give per-architecture governance signatures.

We make three contributions:

1. **A finding.** Decomposition degrades governability, and the mechanism is fact
   attenuation at component boundaries. Summarization at the handoff drops the
   policy-relevant detail: the screening result, the ownership percentage, the identity
   mismatch. The component that violates is not the component that failed.

2. **An instrument.** Fiducia-bench: 100 KYC/AML task variants (generated from 5 seeds),
   machine-checkable policy packs (rules-as-data, each declaring its own verifier type),
   deterministic verification by trajectory replay, and environment-owned audit logs.
   All 10 policy rules are checked without a judge.

3. **A metric family.** Constraint propagation loss, fact attenuation, violation locus,
   authority diffusion — all pure functions of the trajectory and the task
   specification. Historical runs stay re-scorable when verifiers improve.

**Scope and honesty.** This studies an *engineering* decomposition (one task split
across planner, researcher, and decider components), not multi-agent RL in the sense of
agents co-training in a shared environment. The overlap with work on information
survival across time (memory, cross-session continuity) is real but abstract: both
concern whether a fact survives a boundary — theirs across time, ours across components.
We state this at that level, no higher.

---

## 2. Related Work

We organize prior work by what it measures and what it leaves unmeasured, because our
contribution occupies the gap.

**Capability-governance separation.** Corrupt Success [1] introduces the concept by
re-scoring existing benchmarks: an agent that completes a task while violating procedure
is a "corrupt success." They demonstrate that the gap is large and systematic. We share
the framing and extend it to a question they do not ask: does the gap differ across
architectures?

**Paired act/abstain evaluation.** AgentAbstain [2] designs tasks in matched pairs, one
requiring action and one requiring restraint, so an agent cannot improve its score by
always acting. Our escalation metric scores in both directions by construction
(kyc-0001/0005 penalize over-escalation; kyc-0003/0004 penalize under-escalation), and
trigger facts carry `obliges` or `forbids` to express both.

**Hidden policy facts.** PhantomPolicy [3] injects policy-relevant facts that the
agent's context does not contain and tests whether it seeks them out. Our Factor P
(policy access) is a controlled version of this: P0 provides the full policy in
context, P1 makes it retrievable only via a tool. The corpus is identical; only the
access mode differs.

**Escalation calibration.** Act-or-Escalate [4] measures whether agents defer
appropriately when uncertain. Our escalation design differs: correctness is fixed by a
rule hierarchy (a fuzzy sanctions match *must* be frozen and routed to a named team; a
documented two-attribute mismatch on a PEP hit *must not* be escalated), independent of
model confidence.

**Banking-domain benchmarks.** τ³-bench now includes a banking vertical and reports
pass^k. It measures capability, not governance, and does not vary architecture.

**What is genuinely new here.** No prior work gives per-*architecture* governance
signatures. No prior work uses obligation-based escalation (rule mandates, not
confidence calibration). No prior work treats policy packs as portable, machine-checkable
artifacts with declared verifier types. No prior work scores audit reconstructability.
We position this honestly as an integration and domain-depth contribution, not a
first-mover one — several 2026 papers already claim pieces of the space.

---

## 3. Benchmark Design

### 3.1 Environment and tools

The environment is a seeded JSON store with deterministic tools. A `@tool` decorator
registers each tool in a global registry; every call is auto-logged by the environment
with the tool name, arguments, result digest, and — critically — the *actor* that made
the call. The actor is stamped by the arm's topology code, never by the component
itself: a model that writes `"actor": "compliance_officer"` into its output changes
nothing (Section 3.5).

**Invariant 1:** The environment owns the audit log and actor attribution. An agent
never writes its own audit entry.

### 3.2 Policy packs

A policy pack is a YAML file in which each rule declares:
- `rule_id` and `severity` (critical, major, minor)
- `text`: the human-readable rule
- `check`: a machine-readable verification specification

Four check types are implemented: `require_before` (action A must precede action B
when a trigger condition holds), `allow_list` (only whitelisted tools may be called),
`state_assert` (a predicate over the final state), and `forbid_when` (action B is
forbidden while a condition holds). The current pack contains 10 rules; all 10 are
deterministically checkable without a judge.

**Invariant 2:** Verification replays the trajectory against a fresh copy of the
environment, so trigger conditions are evaluated against state *as it was* at the
moment of each tool call — not the final state. This is what makes "if screening
returned a match, escalate before approving" checkable without trusting anything the
agent wrote.

### 3.3 Tasks and trigger facts

Five seed scenarios span constraint distance {0, 1, 2}:

| Task | Scenario | Distance | Obligation direction |
|------|----------|----------|---------------------|
| kyc-0001 | Clean account opening | 0 | Negative: do NOT escalate |
| kyc-0002 | Source-of-funds elicitation | 1 | Positive: request docs |
| kyc-0003 | Fuzzy sanctions match on wire beneficiary | 2 | Positive: freeze + escalate |
| kyc-0004 | Hidden UBO, chained facts | 2 | Positive: elicit → screen → escalate |
| kyc-0005 | Resolvable PEP false positive | 2 | Negative: do NOT escalate |

**Constraint distance** is the number of component boundaries the trigger fact must
cross between the component that discovers it and the component that must act. Under D0
(single loop), distance is always 0; the task's declared distance applies under D1 and
D2.

Each task carries:
- An **oracle script** that achieves governed_success (the unit test for the verifiers)
- At least one **trap script** that satisfies the surface goal while violating policy
- **Trigger facts** with `obliges` or `forbids`, `present_in` tokens for
  boundary-survival checking, and `depends_on` for chained obligations

**Invariant 5:** A task without both a passing oracle and a failing trap is not done.

Tasks 0004 and 0005 are a deliberately paired mirror. Both test whether a fact
survives a component boundary; 0004 drops the risk fact (under-escalation), 0005 drops
the exculpating fact (over-escalation). Together they prevent an agent from gaming the
escalation metric by always escalating: doing so passes 0003/0004 but fails 0001/0005.

**Template expansion.** A deterministic generator (`python -m fiducia.expand`)
produces 100 variant instances from the 5 seeds by varying persona attributes,
jurisdictions, amounts, ownership percentages, and match strengths. Ground-truth flips
are data-driven: lowering a holding company's stake from 26% to 24% moves it below the
25% UBO threshold and flips the correct action from "escalate" to "approve." All 100
variant oracles pass the verifier.

**Invariant 7:** Where an agent asserts a judgment, the environment re-derives it.
`screening.resolve` stores the agent's cited attributes and the environment's finding
(did the cited attributes actually mismatch?) separately. Policy rules read only the
environment's finding.

### 3.4 User simulator

The scripted simulator fires on substring triggers from the task YAML. Hidden
information (deposit size, ownership structure) is disclosed only when the agent's
message matches a trigger, and the disclosure is logged by the environment as a
`Reveal` record — attributable to the component that asked, like any tool call.

An LLM simulator (semantic topic-judge over the same YAML rules) replaces substring
matching with intent matching, so "any other parties with significant ownership
interest?" triggers the ownership disclosure despite zero substring overlap.

### 3.5 Arms (the independent variable)

| Arm | Architecture | Boundaries | Context isolation |
|-----|-------------|------------|-------------------|
| D0 | Single ReAct loop | 0 | Full: one component sees everything |
| D1 | Fixed pipeline: intake → research → decide | 2 | Strict: each stage sees only the previous handoff |
| D2 | Orchestrator + scoped subagents | 2 per round-trip | Strict + tool scoping |

Arms share the same tools, the same policy corpus, and the same ROLE and CONDUCT
prompt blocks. What differs is only the topology paragraph and the context assembly.

**Invariant 8:** The topology assigns identity and context; the component never does.
A brain's output is filtered to a whitelist of action keys and the actor is stamped by
the arm. A component sees a tool result only if it made the call, and a user reply only
if it was active when it arrived. Leaking either across a boundary silently destroys
the effect being measured.

**Factor P (policy access):** P0 pastes the full policy pack into every component's
system prompt. P1 says nothing about the rules and leaves `policy_lookup.search` in the
tool list. The corpus searched by the tool is identical to what P0 provides, so the
comparison isolates access mode, not content.

---

## 4. Metrics

All metrics are pure functions of (trajectory, task YAML). Historical runs stay
re-scorable when verifiers improve (**Invariant 4**).

| Metric | Definition | What it shows |
|--------|-----------|--------------|
| Governed success | Task success ∧ no critical violations ∧ correct escalation | Did it do the right thing, for the right reason, with the right procedure? |
| Propagation loss | Fact discovered but obligated action missing (obliges) or forbidden action taken (forbids) | The mechanism: a fact survived discovery but not the path to action |
| Fact attenuation | Fact discovered, boundary crossed, `present_in` tokens absent from *every* handoff on the path | Where propagation loss happens: at the boundary |
| Violation locus | Actor attribution on the violating tool call | "The component that violates ≠ the component that failed" |
| Authority diffusion | Tool calls an arm refused on scope grounds | D2-specific: the component that found the problem lacked authority to act |
| Chain analysis | `depends_on` → `blocked_upstream`, `chain_broken_at` | For chained obligations: which link failed, and was the downstream fact even reachable? |

**Survival semantics.** A fact survives a boundary only if *every* handoff on the path
from discovery to the acting component carries at least one `present_in` token. `any`
semantics would pass a distance-2 task whose last hop dropped the fact — one faithful
summary and one silent one would score as survived.

**Directional symmetry.** Trigger facts declare either `obliges` (a positive obligation:
the fact mandates an action) or `forbids` (a negative obligation: the fact prohibits an
action). Both score as propagation loss, because under-escalation and over-escalation
are the same mechanism with opposite outcomes. This is not a modeling convenience — it
is the empirical finding: kyc-0004 and kyc-0005 show the same boundary failure producing
opposite governance outcomes on the same model.

---

## 5. Experiments

### 5.1 Setup

We evaluate on Qwen2.5-32B-Instruct-GPTQ-Int4 (32B dense, local vLLM) across all 100
template-expanded task variants and three architectures under P0.

| | Detail |
|---|---|
| Model | Qwen2.5-32B-Instruct-GPTQ-Int4, vLLM 0.11, RTX 5090 |
| Grid | {D0, D1, D2} × P0 × 100 task variants |
| Step budget | 25 per episode |
| Temperature | 0.0, seed=0 |
| Simulator | Scripted (deterministic) |
| **Total episodes** | **300** (100 variants × 3 arms) |

Additionally, a pilot on 5 seed tasks was run on Qwen3-30B-A3B-GPTQ-Int4 (MoE, 3B
active) under P0 and P1 (84 episodes total) to establish the capability floor and test
the P1 factor. Policy-access results (D0×P1 vs D0×P0) showed no systematic difference
on either model.

### 5.2 Results

**Table 1: Full grid (Qwen2.5-32B, n=100 per arm)**

| | D0 | D1 | D2 |
|---|---|---|---|
| Governed success | 0/100 | 3/100 | 1/100 |
| Truncated | 37/100 | 39/100 | 52/100 |
| Fact discovered (any) | 16/100 | 18/100 | 27/100 |
| **Attenuation** | **0** | **9** | **22** |
| Propagation loss | 0 | 4 | 11 |
| Prompt tokens | 3.5M | 4.6M | 4.3M |
| Wall time | 1.4h | 1.9h | 1.8h |

**Finding 1: Attenuation scales with decomposition and is absent from D0.**

The headline result. Conditional on the trigger fact being discovered:

| Constraint distance | D0 | D1 | D2 |
|---|---|---|---|
| 0 | n/a | n/a | n/a |
| 1 | n/a | 0/2 (0%) | 0/1 (0%) |
| **2** | **0/16 (0%)** | **9/16 (56%)** | **22/26 (85%)** |

At distance 2, D0 never attenuates (0/16). D1 attenuates in 56% of discovered-fact
episodes. D2 attenuates in 85%. The effect is large, monotonic in decomposition depth,
and absent from the control arm. Distance 0 and 1 produce no attenuation on any arm,
confirming that the effect requires a boundary to cross.

**Finding 2: The same mechanism produces opposite governance outcomes.**

kyc-0004 (positive obligation: elicit ownership → screen UBO → escalate) and kyc-0005
(negative obligation: gather attributes → document mismatch → do NOT escalate) are a
paired mirror. At distance 2:

| | kyc-0004 D2 | kyc-0005 D2 |
|---|---|---|
| Discovered | 10/25 | 16/25 |
| Attenuation | 8/10 (80%) | 14/16 (88%) |
| Outcome when attenuated | UBO never screened → under-escalation | Mismatch not carried → over-escalation |

In both, summarization at the boundary drops what the summarizer considers secondary.
The component that violates is not the component that failed: the decider acts
reasonably on what it received. The researcher screens diligently. The obligation is
lost between them.

**Finding 3: D2 discovers more facts but loses more of them.**

D2 discovers trigger facts in 27/100 episodes vs D0's 16/100 — the orchestrator's
structured delegation ("screen this person", "check if this is a false positive") elicits
more information than D0's unguided loop. But D2 also attenuates 22 of those 27
discoveries (81%), while D0 attenuates none. The architecture that is better at
*finding* the policy-relevant fact is worse at *carrying* it to the component that must
act. This is not a capability-governance tradeoff in the usual sense — it is the same
capability producing more governance failures because the architecture has more
boundaries to lose it at.

**Finding 4: Policy visibility is not the driver.**

D0×P0 vs D0×P1 on the 5 seed tasks (both models) shows no systematic difference in
governed success, truncation, or violation rates. The kill criterion stated before data
collection — if P1 alone explains the degradation, retitle the paper — is not met.
Decomposition, not policy access mode, is the driver at this model scale.

### 5.3 Limitations

**Model scale.** Governed success is 4/300 (1.3%). The benchmark is harder than the
models we can run locally. The confirmed effect (attenuation rates of 56–85% at
distance 2) is large and stable, but the headline chart — governed *success* rate vs
constraint distance, per arm — requires a model that occasionally passes under D0, so
the degradation shows as a rate declining from a nonzero baseline. A frontier model
would provide this; we report the attenuation metric directly.

**Scripted simulator.** Substring triggers measure phrasing luck alongside governance.
The LLM simulator (semantic topic-judge) exists and is verified but was not used for
the reported episodes, to preserve determinism. This likely depresses discovery rates:
a model that asks about ownership in different words gets no response, inflating
truncation and deflating the denominator of the attenuation rate. The conditional
attenuation rate (given discovery) is unaffected.

**Single model for the full grid.** The 300-episode grid uses Qwen2.5-32B only. The
pilot on Qwen3-30B-A3B (3B active, 39 episodes) confirmed the same attenuation signal
on kyc-0005 D2 at k=4, but sat below the capability floor for most tasks. A third
model (ideally frontier-scale) would strengthen the generalization claim.

**Prompt confound.** The CONDUCT block was tuned against the five seed tasks, not a
held-out set. We froze it before data collection and report it as such. All prompts
are published in Appendix C.

---

## 6. Discussion

**For the verification community.** The benchmark is an environment-grounded verifier
that composes heterogeneous signals — deterministic state checks, tool-call sequencing,
handoff-payload inspection, and audit-log completeness — into a governed_success
verdict. It is reproducible without a judge for over 70% of its rules, and the
remainder could be added with calibrated judges without changing the architecture.

**For agent builders.** If you are building a multi-component agent system for a
regulated domain, the handoff summary is a governance-critical surface. Attenuation
there produces failures that no individual component is responsible for and that
capability benchmarks cannot see. The practical implication: structured handoff
protocols (what to include, what to verify, what to refuse to summarize) are a
governance intervention, not just an engineering convenience.

**For evaluation designers.** Three design choices proved load-bearing: (1) the
environment owns attribution, not the agent; (2) verification replays state, not reads
final state; (3) both directions of escalation are tested, so the metric cannot be
gamed by always escalating. We recommend these for any governance benchmark.

---

## 7. Conclusion

We introduced Fiducia-bench, a benchmark for agent governability in regulated
workflows, and used it to show that decomposing an agent into components degrades its
policy compliance through a specific mechanism: fact attenuation at handoff boundaries.
The same mechanism produces both under-escalation (risk facts dropped) and
over-escalation (exculpating facts dropped). The benchmark, its policy packs, all
tasks, and the verification harness are open-source.

What we did not show: that this holds for frontier models (our strongest local model
scores 0% governed success), that it generalizes beyond KYC/AML (the mechanism is
domain-general but the tasks are not), or that it cannot be fixed by better prompting
(it probably can, and measuring how much is future work). We state these honestly
because a reviewer who discovers them is a worse outcome than an author who says so.

---

## References

[1] Corrupt Success. arXiv 2603.03116, 2026.
[2] AgentAbstain. arXiv 2607.10059, 2026.
[3] PhantomPolicy. arXiv 2604.12177, 2026.
[4] Act-or-Escalate. arXiv 2604.08588, 2026.
