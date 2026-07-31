# Fiducia — Novelty Sweep (July 2026)

**Verdict up front: the gap shrank a lot.** Between roughly March and July 2026, four
papers independently published pieces of what we scoped as Fiducia's contributions. The
headline framing ("first benchmark for agent governability") is **dead**. A narrower,
honest contribution survives — and there is a stronger reframing available (see §4).

---

## 1. Direct hits — these take something we claimed

| Work | What it is | What it takes from us | What it leaves open |
|------|-----------|----------------------|--------------------|
| **Beyond Task Completion: Corrupt Success via Procedure-Aware Evaluation** (arXiv 2603.03116, Mar 2026) | Re-scores an existing agent benchmark with procedure-aware gating; finds 27–78% of reported successes are "corrupt successes" concealing violations; gating collapses Pass^4 and reorders model rankings | **The core concept.** "Corrupt success" ≈ our governed-success gap, including the pass^k-collapse result. Our money chart is their headline. | It is an *evaluation lens re-applied to an existing benchmark*, not a domain environment. No regulated-domain tasks, no rules-as-data format, no escalation obligation, no auditability. |
| **AgentAbstain** (arXiv 2607.10059, Jul 2026) | 263 **paired** tasks across 42 executable environments; every should-act task has a should-abstain twin via controlled perturbation; 8 abstention scenarios; deterministic commit check × LLM judge; best of 17 frontier models <60% of pairs | **The mirror-pair design** (our 0004/0005 construction) and the both-directions insight — over-abstention is scored, not just under-abstention. | Abstention is triggered by *ambiguity, contradiction, or tool failure*. Not by a domain rule that says "this specific match type must route to this specific team." No policy corpus, no domain depth. |
| **Policy-Invisible Violations / PhantomPolicy** (arXiv 2604.12177, Apr 2026) | 8 violation categories, balanced violation/safe-control cases, where the decisive policy facts are **absent from the agent's visible context** (tool responses carry clean business data, no policy metadata); 600 traces human-reviewed across 5 frontier models; plus "Sentinel," a reference enforcement layer over a structured world model | **The hidden-info-drives-violation design.** Our `hidden_info` mechanism is their central construct. | Enforcement is architecturally separated as their proposed *fix*; the benchmark is cross-domain and generic. No regulated workflow depth, no escalation targets, no audit scoring. |
| **Act or Escalate?** (arXiv 2604.08588, Apr 2026) | Escalation behavior across 8 models on 5 decision tasks (incl. loan approval); models escalate when estimated correctness falls below a cost-derived threshold; finds LLMs both miscalibrated and inconsistent | **Escalation as a measured behavior**, with a cost-weighted framing. | Escalation is modeled as a **confidence-calibration** decision (defer when unsure). Not as a **mandatory obligation with a named correct recipient**, which is what regulation actually specifies. This distinction is our opening — see §3. |

## 2. Adjacent — cite, don't fear

| Work | What it is | Why it isn't us |
|------|-----------|-----------------|
| **CompliBench** (2604.12312) | Benchmarks LLM **judges** on detecting/localizing guideline violations in multi-turn dialogue; flaw injection yields turn-level ground truth; a fine-tuned small judge beats frontier models | Evaluates the *grader*, not the agent. Useful to us as prior art for judge calibration methodology. |
| **Solver-aided policy compliance verification** (2603.20449) | Formal solver checks each tool call before execution on τ-bench; UNSAT blocks the call and returns a minimal unsat core for replanning | A *method/enforcement layer*, not a benchmark. Closest relative to our deterministic verifier idea — cite as evidence that formal checking of tool-call policy is tractable. |
| **τ³-bench** (in sierra-research/tau2-bench, Jul 2026) | Third generation of the τ line: adds a `banking_knowledge` RAG-retrieval domain, full-duplex voice, 75+ task fixes. τ-bench originated pass^k + policy adherence; τ² added dual control | The τ line is now **in banking** — but as knowledge retrieval for customer service, not regulated case handling. Note also that v1.0.1 re-graded banking tasks, so version-pin any comparison. |
| **FinToolBench** | 760 executable financial tools, 295 tool-required queries, compliance dimensions (timeliness, intent type, regulatory-domain alignment), FATR baseline | Tool-selection and execution compliance, single-shot-ish. No multi-turn hidden info, no escalation, no case lifecycle. |
| **Copyright-Bench** (2607.21799, Jul 2026) | Agentic legal-compliance eval: does the model choose the compliant action when infringement is available, under neutral / IP-aware / IP-dismissive prompts | Confirms our **trap** design is now standard practice in another legal domain. Cite for the trap methodology; the prompt-framing axis is a good idea worth borrowing. |
| **FinAgentBench** (2508.14052) | Agentic retrieval ranking over S&P 500 filings | Retrieval/IR only. Still our cleanest "existing financial agent evals are retrieval-shaped" citation. |
| **TransXion** (2604.17420) | High-fidelity synthetic AML transaction-graph benchmark | Graph ML on transactions, not LLM agents. Useful if we ever need realistic transaction data for a monitoring track. |

## 3. What actually survives

Four things, none of which any single work above claims:

1. **Obligation-based escalation, not confidence-based deferral.** Act-or-Escalate asks
   "is the model calibrated about its own accuracy?" AgentAbstain asks "does it notice the
   task is unsound?" Regulation asks neither: it says *a fuzzy sanctions match must be
   frozen and routed to the sanctions team, and a documented two-attribute identity
   mismatch on a PEP hit must NOT be escalated.* Correctness is fixed by a rule hierarchy,
   independent of the agent's uncertainty. That is a distinct construct and, as far as this
   sweep shows, unmeasured.
2. **Policy packs as portable, machine-checkable artifacts.** Rules-as-data with a declared
   verifier type per rule (`require_before` / `allow_list` / `state_assert`), ≥70%
   deterministically checkable, evaluated by **replaying** the trajectory so triggers fire
   against state as-it-was. Others hard-code checks, use a solver as an enforcement layer,
   or defer to judges. A rule format others can extend is a real artifact contribution.
3. **Audit reconstructability as a scored metric.** Environment-owned audit log; a scripted
   auditor must answer who/what/why/when/under-which-rule from the log alone. Found nothing
   scoring this. It is also the thing regulators explicitly ask for.
4. **Domain depth in obligation-dense workflows** — KYC/EDD/UBO/suitability with a rule
   hierarchy deep enough that rules interact (sanctions never self-clearable vs. PEP
   false-positive resolvable under documentation). Generic cross-domain benchmarks cannot
   produce that interaction structure.

Honest downgrades to internalize: pass^k was never ours (τ-bench); traps are now standard;
paired mirrors are AgentAbstain's; hidden-fact-driven violation is PhantomPolicy's;
capability-vs-governed gap is Corrupt Success's. Fiducia is now an **integration +
domain-depth** contribution, not a first-mover one. That is publishable at a workshop. It
is not an ICLR main-track story on its own.

## 4. Stronger reframing — make the paper a *finding*, not a dataset

A benchmark alone now enters a crowded field. A benchmark that answers a question does not.
The question our own architecture makes available:

> **Does decomposing an agent degrade its governability?**

Run single-agent vs. plan→research→synthesize (the architecture pattern already in the
roadmap) over identical tasks and measure where governance fails: does the planner shed the
policy constraint, does the synthesizer approve what the researcher flagged, does escalation
recall drop as coordination depth grows? Corrupt Success shows per-model failure signatures;
nobody has shown per-**architecture** governance signatures. This is a genuine result, it
needs exactly the instrument we are building, and it speaks directly to labs working on
multi-agent RL — which is also the audience we care about.

Secondary differentiator still unclaimed by anything in this sweep: **bilingual (EN+ZH)
regulated workflows** — does governance hold when the policy corpus and the conversation are
in different languages? Cheap to state, genuinely novel, ~30% more work.

## 5. Sweep coverage — what is still unchecked

- Insurance / healthcare regulated-agent benchmarks (adjacent obligation-dense domains)
- "Audit trail / provenance" as an agent metric (searched only obliquely)
- Non-English financial compliance agent evals
- Commercial/industry evals (Vals AI and similar) that may not publish to arXiv
- Reward-hacking and specification-gaming literature — likely has the obligation-vs-preference
  distinction under different vocabulary
