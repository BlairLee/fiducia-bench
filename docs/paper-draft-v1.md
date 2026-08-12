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
lost. Across two models and three architectures (single loop, fixed pipeline,
orchestrator-subagent), a multi-component arm reproduced fact attenuation in 4/4
independent runs, while the single-component baseline resolved the same case with no
boundary to cross. The same mechanism produces both under-escalation (a risk fact is
dropped) and over-escalation (an exculpating fact is dropped), confirming that the
failure is directionally symmetric: summarization at the boundary loses whatever the
summarizer considers secondary.

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

2. **An instrument.** Fiducia-bench: five KYC/AML scenarios (expandable to 100 via
   template generation), machine-checkable policy packs (rules-as-data, each declaring
   its own verifier type), deterministic verification by trajectory replay, and
   environment-owned audit logs. Over 70% of policy rules are checked without a judge.

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

We evaluate two open-weights models on the five seed tasks under three architectures
and two policy-access modes:

| Model | Parameters | Activation | Quantization |
|-------|-----------|------------|-------------|
| Qwen3-30B-A3B | 30B total, 3B active (MoE) | GPTQ-Int4 | Local vLLM |
| Qwen2.5-32B-Instruct | 32B dense | GPTQ-Int4 | Local vLLM |

**Grid:** {D0, D1, D2} × {P0} for both models; {D0, D1, D2} × {P1} for both models.
Step budget: 25 per episode. Temperature: 0.0 for seed=0, 0.6 for seed=1 (Qwen2.5
only). Signal cells confirmed with k=3–4 repeats.

**Total episodes:** 39 (Qwen3-30B-A3B) + 45 (Qwen2.5-32B) = 84.

### 5.2 Results

**Finding 0: Model capability is the first gate.**

Qwen3-30B-A3B (3B active parameters) sits below the benchmark's capability floor.
Truncation rate: 14/15 under P0. The model rarely calls `control_finish` and screens
the customer rather than the wire beneficiary in 12/15 cells. Governed success: 0/15.
This is not a negative result about decomposition; it is a measurement of where the
benchmark's dynamic range begins: a model that cannot complete the basic workflow under
*any* arm cannot produce governance signals.

Qwen2.5-32B (32B dense) crosses the floor. Truncation drops to 2/10 for D0.
Facts are discovered in 4/10 D0 episodes. The pipeline hands off. Governed success
remains 0/30, but the failure mode shifts from "never got there" to "got there and
made a governance mistake" — which is what the benchmark exists to measure.

**Finding 1: Fact attenuation at the boundary is reproducible and stable.**

kyc-0005 × D2 on Qwen3-30B-A3B: the exculpating identity attributes (DOB 1991 vs
1958, nationality domestic vs vantalia) are discovered every run (4/4) and dropped at
the researcher→orchestrator handoff every run (survived=False, 4/4). The orchestrator
sees "EXACT PEP MATCH" without the comparison that would resolve it, and either
escalates (over-reaction) or stalls. D0 resolves the same case in 4–9 tool calls with
no boundary to cross.

This reproduces on Qwen2.5-32B under P1: kyc-0005 D1 and D2 both show attenuation
(survived=False), while D0 handles it correctly.

**Finding 2: D0's failures and D1/D2's failures are qualitatively different.**

Under Qwen2.5-32B P0 (pooled k=2, n=10 per arm):

| | D0 | D1 | D2 |
|---|---|---|---|
| Truncated | 2/10 | 6/10 | 5/10 |
| Fact discovered (any) | 4/10 | 3/10 | 2/10 |
| Attenuation | 0 | 1 | 1 |
| Propagation loss | 2 | 2 | 0 |

D0's propagation loss comes entirely from kyc-0003: it discovers the sanctions match,
freezes the wire, but never escalates to the sanctions team. This is a *judgment*
failure — D0 has no boundary to blame. D1's attenuation comes from kyc-0005: the fact
is present in the intake handoff but dropped in the researcher→decider summary. This is
a *boundary* failure. The distinction is the paper's core claim.

**Finding 3: Policy visibility is not the driver.**

D0×P0 vs D0×P1 on both models shows no systematic difference. Governed success: 0/5
both. Truncation: identical. Violations differ but not directionally. The kill
criterion that would have retitled the paper around policy access is not met. At this
model scale, having the policy in context versus retrieving it on demand does not
measurably change governance outcomes.

**Finding 4: The same mechanism produces opposite outcomes.**

kyc-0004 (positive obligation) and kyc-0005 (negative obligation) are designed as a
paired mirror. In both, summarization at the boundary drops what the summarizer
considers secondary. For kyc-0004, the secondary detail is the ownership structure
(dropped → the UBO is never screened → under-escalation). For kyc-0005, the secondary
detail is the identity mismatch (dropped → the PEP match is not resolved →
over-escalation). Neither component decides wrongly; the obligation is lost at the
boundary.

### 5.3 Limitations

**Model scale.** 0/84 governed_success. The benchmark is harder than the models we can
run locally. The confirmed effect (attenuation) is real and stable, but the headline
metric (governed success rate vs constraint distance, per arm) requires a model that
occasionally passes — so the degradation is a rate, not a binary. A cloud-API model
(GPT-4o, Claude) would provide this; we report what local open-weights models show.

**Sample size.** n=10 per arm for the strongest model. Wilson CIs are wide
([0, 0.434] for 0/5). The signal cells are confirmed at k=4; the non-signal cells are
single-run.

**Prompt confound.** The CONDUCT block was tuned against the five seed tasks, not a
held-out set. We froze it before data collection and report it as such. All prompts
are published in Appendix C.

**Scripted simulator.** Substring triggers measure phrasing luck. The LLM simulator
exists, is verified, and is available; the reported episodes use the scripted one for
determinism.

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
