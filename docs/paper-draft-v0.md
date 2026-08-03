# Governance at the Boundary: How Agent Decomposition Degrades Policy Compliance

**Target venues (dual submission, both non-archival):**
- Primary: [Who Verifies the Agents?](https://verify-agents-workshop.github.io/) @ NeurIPS 2026
  → Pillar 2 (environment-grounded verification) + Pillar 3 (heterogeneous verifiable signals)
- Secondary: [Evaluation of Interactive Agents](https://eval-interactive-agents-workshop.github.io/) @ NeurIPS 2026
  → trajectory-level evaluation + grader design + user simulation

**Format:** 4–9 pages (excl. references/appendices), NeurIPS 2026 template, double-blind.
**Deadline:** August 29, 2026 AoE (27 days from Aug 2).

---

## Paper outline

### Abstract (~150 words)

Agent benchmarks measure whether the agent finished the task. We measure whether it
finished it **within policy**. We introduce fiducia-bench, a benchmark for the
*governability* of financial agents — whether they escalate when obligated, abstain when
required, and leave an auditable trail — and use it to study a question no existing
benchmark answers: **does decomposing an agent into components degrade its governance?**

We find that it does, and the mechanism is specific: policy-relevant facts discovered by
one component are **attenuated at the handoff boundary** before reaching the component
that must act on them. In a controlled experiment over five KYC/AML scenarios, a
multi-component architecture (orchestrator + subagent) reproduced fact attenuation at
the boundary in 3/3 independent runs, while the single-component baseline resolved the
same case in 4 steps with no boundary to cross.

The benchmark, all tasks, and the verification harness are open-source.

---

### 1. Introduction (~1 page)

**Opening hook:** Enterprise agent systems are moving from single ReAct loops to
orchestrator/subagent architectures. The motivation is engineering (modularity, tool
scoping, specialization). The unasked question: does this decomposition degrade the
agent's ability to comply with the rules that govern its work?

**The gap:** Existing benchmarks measure decomposition's effect on *capability* (task
completion). Four recent works measure governance independently: Corrupt Success
(2603.03116) re-scores capability benchmarks with procedure-awareness; AgentAbstain
(2607.10059) pairs should-act/should-abstain tasks; PhantomPolicy (2604.12177) hides
policy facts from the agent's context; Act-or-Escalate (2604.08588) measures escalation
calibration. None varies the *architecture* while holding the task and model constant.

**Our contribution (three things):**
1. **A finding:** decomposition degrades governability, and the mechanism is fact
   attenuation at component boundaries — summarization at the handoff drops the
   policy-relevant detail. The component that violates is not the component that failed.
2. **An instrument:** fiducia-bench — five KYC/AML scenarios with machine-checkable policy
   packs, deterministic verifiers, environment-owned audit logs, and scripted + LLM user
   simulators. ≥70% of policy rules are checked without a judge.
3. **A metric family:** constraint propagation loss, fact attenuation, violation locus,
   authority diffusion, audit reconstructability — all pure functions of the trajectory,
   all re-scorable when verifiers improve.

**Scope and honesty (do not skip):** This studies an *engineering* decomposition pattern
(task split across components), not multi-agent RL. The overlap with work on information
survival across time (memory, cross-session continuity) is real but abstract. This is an
integration + domain-depth contribution, not a first-mover one. Say so.

---

### 2. Related Work (~0.75 page)

Organized by what each work measures and what it leaves open. Table format:

| Work | Measures | Does not measure |
|------|----------|-----------------|
| Corrupt Success (2603.03116) | capability-vs-governed gap | per-architecture signatures |
| AgentAbstain (2607.10059) | paired act/abstain, both directions | obligation-based (vs. ambiguity-based) |
| PhantomPolicy (2604.12177) | hidden-fact-driven violations | decomposition effect |
| Act-or-Escalate (2604.08588) | escalation calibration | rule-mandated routing |
| τ³-bench | pass^k, banking domain | regulated case lifecycle |
| CompliBench (2604.12312) | judge accuracy | agent behavior |

**What is genuinely new here:**
- Obligation-based escalation (rule hierarchy, not confidence calibration)
- Policy packs as portable artifacts (rules-as-data with declared verifier types)
- Audit reconstructability as a scored metric
- Per-architecture governance signatures (the decomposition question)

---

### 3. Benchmark Design (~1.5 pages)

#### 3.1 Environment and tools

Seeded JSON state, deterministic tools (@tool registry), environment-owned audit log.
Agent cannot write its own audit entry or declare its own actor (Invariant 1).

#### 3.2 Policy packs

Machine-readable YAML. Each rule declares its check type: `require_before`,
`allow_list`, `state_assert`, `forbid_when`. Verification replays the trajectory against
a fresh environment (Invariant 2). Currently 10 rules, ≥70% deterministically checkable.

#### 3.3 Tasks and trigger facts

Five KYC/AML scenarios spanning constraint_distance {0, 1, 2}:

| Task | Scenario | Distance | Obligation |
|------|----------|----------|------------|
| kyc-0001 | Clean account opening | 0 | Negative: do NOT escalate |
| kyc-0002 | Source-of-funds elicitation | 1 | Positive: request docs before approving |
| kyc-0003 | Fuzzy sanctions match on wire beneficiary | 2 | Positive: freeze + escalate to sanctions team |
| kyc-0004 | Hidden UBO, chained facts | 2 | Positive: elicit ownership → screen UBO → escalate |
| kyc-0005 | Resolvable PEP false positive | 2 | Negative: do NOT escalate, document mismatch |

Each task carries an oracle script (governed_success=True) and at least one trap script
(governed_success=False). Tasks 0004 and 0005 are a paired mirror: same mechanism
(summarization drops a fact at the boundary), opposite outcomes (under- vs.
over-escalation).

**Trigger facts** declare `obliges` or `forbids`, `present_in` tokens for
boundary-survival checking, and `depends_on` for chained obligations.

#### 3.4 Simulator

Scripted (substring-trigger, deterministic) and LLM (semantic topic-judge over the same
YAML rules, canned replies preserved for deterministic downstream scoring). The LLM
simulator uses a separate model from the agent to avoid self-consistency bias.

#### 3.5 Arms (the independent variable)

| Arm | Architecture | Boundaries |
|-----|-------------|------------|
| D0 | Single ReAct loop | 0 |
| D1 | Fixed pipeline: intake → research → decide | 2 |
| D2 | Orchestrator + scoped subagents | 2 per delegation round-trip |

All arms share the same tools, the same policy corpus, and the same CONDUCT prompt.
What differs is ONLY the topology paragraph and the context isolation. A component
cannot name itself (stamp), cannot see upstream tool results (ComponentContext), and
cannot exceed its tool scope (arm refuses, logs the attempt).

**Factor P** (policy access): P0 pastes the full policy pack into context; P1 makes it
available only through `policy_lookup.search`. Same corpus, different access mode.

---

### 4. Metrics (~0.75 page)

All are pure functions of (trajectory + task YAML). Historical runs stay re-scorable
when verifiers improve (Invariant 4).

| Metric | Definition | What it shows |
|--------|-----------|--------------|
| **Governed success** | Task success AND no critical violations AND correct escalation | The headline: did it do the right thing for the right reason? |
| **Constraint propagation loss** | Fact discovered, obligated action missing (obliges) or forbidden action taken (forbids) | The mechanism: information survived discovery but not the path to action |
| **Fact attenuation** | Fact discovered, boundary crossed, present_in tokens absent from handoff payload | Where propagation loss happens: at the boundary |
| **Violation locus** | Which component issued the violating call | The signature: "the component that violates ≠ the component that failed" |
| **Authority diffusion** | Blocked calls (component tried a tool outside its scope) | D2-specific: the component that found the problem lacked authority to act |
| **Audit reconstructability** | 5-dimensional score: who/what/when/why/under-which-rule answerable from the env-owned log | The regulator's question: can you reconstruct what happened? |

---

### 5. Experiments (~1.5 pages)

#### 5.1 Setup

- Model: Qwen3-30B-A3B-GPTQ-Int4 (local vLLM, temperature=0, seed pinned)
- Arms: D0, D1, D2 × P0; D0 × P1
- Tasks: all 5 seed scenarios
- Budget: 25 steps per episode
- Repeats: k=3 on signal cells, k=1 baseline elsewhere
- Simulator: scripted (deterministic)

#### 5.2 Results

**Table 1: Sweep summary** — per-arm governed_success, truncation rate, escalation
accuracy, mean cost.

**Finding 1: Fact attenuation at the boundary is reproducible.**
kyc-0005 × D2: attenuation = 3/3 runs. The PEP match is discovered every time
(discovered=3/3). The exculpating half (DOB/nationality mismatch) is dropped at the
orchestrator→researcher handoff every time (survived=False, 3/3). D0 resolves the same
case in 4 tool calls with no boundary to cross.

**Figure 1** (the headline figure): Governance failure rate vs. constraint_distance, one
line per arm. Even with limited data, D2 at distance=2 shows consistent attenuation
that D0 does not.

**Finding 2: The component that violates is not the component that failed.**
In kyc-0005 D2, the orchestrator triggers KYC-05b (approves without documented
resolution). But the orchestrator acted reasonably on what it received — the researcher's
handoff dropped the nationality mismatch. Violation locus ≠ failure locus.

**Finding 3: Termination is a systematic problem at this model scale.**
18/19 P0 episodes truncated (hit step cap). The model rarely calls control_finish. This
is a capability floor, not a benchmark bug — report truncation rate alongside
governed_success.

**Finding 4 (if data supports): P1 vs P0.**
Currently both at floor. Report honestly: the model is too weak to separate policy
access modes. This is a null result worth stating.

#### 5.3 Limitations

- **Model scale:** 30B-GPTQ is at the capability boundary. Most cells show capability
  failure, not governance failure. The confirmed effect (kyc-0005 D2) is real but the
  benchmark needs a stronger model for the full grid.
- **k=1 for most cells:** Statistical power is limited. The k=3 confirmation on the
  signal cell is the strongest claim; everything else is pilot-grade.
- **Prompt confound:** CONDUCT was tuned against the seed tasks (documented in commit
  history). Either re-tune on held-out tasks or report as fixed-before-data-collection.
- **Scripted simulator:** Substring triggers measure phrasing luck. The LLM simulator
  exists and is verified but was not used for the reported episodes.

---

### 6. Discussion (~0.5 page)

**Why this matters for the verification community (Verify-Agents framing):**
The benchmark is an environment-grounded verifier (Pillar 2) that uses heterogeneous
signals — deterministic state checks, tool-call sequencing, handoff-payload inspection,
and audit-log completeness — composed into a governed_success verdict (Pillar 3).

**Why this matters for agent evaluation (IAEval framing):**
Trajectory-level assessment (not just final outcome), deterministic graders that don't
need a judge for 70%+ of rules, and user simulation design (scripted vs. LLM, with
explicit validity tradeoffs).

**The actionable takeaway:** If you are building a multi-component agent system for a
regulated domain, the handoff summary is a governance-critical surface. Attenuation
there produces failures that no individual component is responsible for and that
capability benchmarks cannot see.

---

### 7. Conclusion (~0.25 page)

Restate the finding, the instrument, and the metric family. Note what is not claimed
(not multi-agent RL, not a solved problem, not legal advice). Point to the open-source
repo.

---

### Appendices (not counted toward page limit)

- **A.** Full policy pack text (all 10 rules)
- **B.** Task YAML excerpts (one oracle, one trap per task)
- **C.** Prompt text for all arms (ROLE, CONDUCT, topology paragraphs, case block)
- **D.** Per-episode detail table (all 39 episodes: 15 sweep1 + 24 sweep2)
- **E.** Template expansion: variation axes and ground-truth flip verification

---

## Writing plan

| Section | Status | Depends on | Target date |
|---------|--------|------------|-------------|
| 3 (Benchmark Design) | Can write now | Nothing | Aug 5 |
| 4 (Metrics) | Can write now | Nothing | Aug 5 |
| 2 (Related Work) | Can write now | Novelty sweep done | Aug 7 |
| 1 (Introduction) | After 2,3,4 | Framing settled | Aug 10 |
| 5 (Experiments) | Needs more data | Stronger model or k=3 all cells | Aug 18 |
| 6,7 (Discussion, Conclusion) | After 5 | Results in hand | Aug 22 |
| Abstract | Last | Everything | Aug 25 |
| Formatting, anonymization | Last | Everything | Aug 28 |

**Hard deadline: August 29, 2026 AoE.**

---

## Anonymization checklist (double-blind)

- [ ] Remove author names and affiliations
- [ ] Remove GitHub repo URL from the paper body (put in supplementary/anonymous repo)
- [ ] Remove any reference to "the author's employer" or day-job constraints
- [ ] Check that CLAUDE.md's "Hard boundary" section is not quoted verbatim
- [ ] Use "we" throughout, not "I"
- [ ] Anonymous supplementary: create an anonymous GitHub or use OpenReview supplementary
