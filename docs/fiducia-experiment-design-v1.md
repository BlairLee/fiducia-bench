# Fiducia — Experiment Design v1

**Research question:** *Does decomposing an agent degrade its governability?*

The paper's claim is not a leaderboard. It is a mechanism: governance obligations fail at
**boundaries** — between reasoning steps, between components, between what one component
discovered and what another component decides. Fiducia is the instrument that isolates it.

Working title: *Governance at the Boundary: How Agent Decomposition Degrades Policy
Compliance in Regulated Workflows.*

---

## 1. Factor design

Two orthogonal factors, because "multi-agent is worse" is uninteresting unless you separate
*decomposition* from *what each component can see*.

**Factor D — decomposition**
| Arm | Description |
|-----|-------------|
| `D0` single ReAct loop | One agent, one context, tools called directly. Baseline. |
| `D1` fixed pipeline | plan → research → synthesize/decide. Sequential, no dynamic routing. Each stage receives only the previous stage's output. |
| `D2` dynamic subagents | Orchestrator delegates to subagents with narrowed tool scopes; subagents return summaries, orchestrator decides. |

**Factor P — policy access**
| Arm | Description |
|-----|-------------|
| `P0` full in-context | Entire policy pack text in every component's system prompt. |
| `P1` retrieval on demand | Components must call `policy_lookup.search` to see rules; nothing in context. Models the skill-based pattern where policy is a tool, not a prompt. |

**Core grid (4 arms):** D0×P0, D0×P1, D1×P0, D2×P0.
**Optional extension (2 arms):** D1×P1, D2×P1 — run only if the core grid shows an effect.

Rationale: D0×P1 vs D0×P0 isolates policy visibility *without* decomposition. If P1 alone
explains most of the degradation, the finding is "policy-as-a-tool is the problem, not
decomposition" — which is a more surprising and more useful result than the expected one.

## 2. Dependent variables

**Carried over (from schema v0):** governed success (pass^k), task success, critical
violation rate, escalation precision/recall, audit reconstructability.

**New, decomposition-specific — this is the paper's intellectual core:**

| Metric | Definition | How measured |
|--------|-----------|--------------|
| **Constraint propagation loss** | Trigger fact is discovered by component A; the obligated action is taken (or not) by component B. Rate at which B fails to act on a fact A possessed. | Requires per-component attribution; deterministic given actor-tagged trajectory |
| **Fact attenuation** | Is the trigger fact present in the handoff payload that crosses A→B? | Inspect handoff messages: exact-value match on the trigger fact (e.g. `list: sanctions`, UBO id), plus judge for paraphrase |
| **Violation locus** | Which component issued the forbidden/critical call | Actor field on every tool event; yields per-architecture governance signatures |
| **Escalation authority diffusion** | In decomposed arms, whether escalation is dropped because no component owns it (vs. actively decided against) | Escalation missing AND no component's output mentions the trigger → diffusion, not judgment |

Fact attenuation is the mechanism claim: if degradation tracks attenuation, the story is
"summarization at the boundary drops policy-relevant facts," which is concrete, actionable,
and directly relevant to anyone building multi-agent systems.

## 3. The key task property: constraint distance

Define per task **constraint distance** = the number of component boundaries the trigger fact
must cross between discovery and obligated action.

| Task | Discovery → obligation path | Distance under D1/D2 |
|------|---------------------------|---------------------|
| kyc-0001 | none (no trigger) | 0 |
| kyc-0002 | user reveals deposit size → request SoF before approval | 1 |
| kyc-0003 | screening returns fuzzy sanctions → freeze + route | 1–2 |
| kyc-0004 | elicit ownership → screen hidden UBO → withhold approval | 2–3 |
| kyc-0005 | gather attributes → document FP resolution → approve without escalating | 2–3 |

**The paper's money chart becomes: governance failure rate vs. constraint distance, one line
per architecture.** If the lines fan out with distance, the mechanism is demonstrated. This
is a much stronger figure than a bar chart of model scores.

**Immediate consequence for the build order:** 0003/0004/0005 are now the high-value tasks
because they have multi-boundary dependency structure; 0001/0002 are controls. Build them
next, before scaling task count.

## 4. Controls and confounds (state these explicitly in the paper)

- **Context budget differs across arms.** D0 sees everything; subagents see less. This is
  partly *the mechanism*, not just a confound — but report tokens-in per episode per arm, and
  note that D0's advantage may vanish at longer horizons where its context saturates.
- **Prompt quality per arm.** Risk of strawmanning a decomposed arm with a lazy prompt.
  Mitigation: tune all arm prompts on the held-out 20% of seed tasks only, publish every
  prompt verbatim, and report per-arm prompt iteration counts.
- **Model × architecture interaction.** Need ≥3 models before claiming anything general; a
  single-model result is an anecdote. Include at least one open-weights model so others can
  reproduce without API budget.
- **Judge dependence.** Keep ≥70% of rule checks deterministic so the headline result does not
  rest on the judge. Report judge/human agreement on the calibration set.
- **Simulator artifacts.** Corrupt Success (2603.03116) specifically calls out simulator
  artifacts producing accidental successes. Audit a sample of passes by hand and report the
  accidental-success rate — doing this proactively is a credibility win.

## 5. Infrastructure changes required

Ordered by dependency:

1. **`actor` field on every tool event and audit-log entry.** Without attribution, none of the
   new metrics compute. Touches `EnvState.log`, `ToolEvent`, `runner`.
2. **Handoff payloads as first-class logged objects.** New `Handoff` record: `from`, `to`,
   `payload`, `seq`. This is what fact-attenuation is measured over.
3. **Trigger-fact registry per task.** Each task declares its trigger facts with machine-
   checkable values (`{list: sanctions}`, `ubo_id: corvex_ubo`) so attenuation is checkable
   without a judge.
4. **Arm harness.** One class per arm over the shared tool layer; arms differ only in
   orchestration and prompt assembly, never in tool access semantics.
5. **`constraint_distance` annotation** on each task (per arm, since D0 has distance 0 by
   construction).
6. Then: LLM simulator, then baselines.

## 6. Cost model — pilot before committing

Full grid is multiplicative: 4 arms × 100 tasks × k=4 × 4 models = 6,400 episodes, and
decomposed arms cost 2–4× more LLM calls per episode than D0.

**Pilot first:** 20 tasks × 4 arms × 2 models × k=2 = 320 episodes. Measure tokens and wall
time per episode per arm, then size the full run. Run the open-weights model locally to keep
the pilot near-free; reserve API budget for the final grid only.

## 7. Revised week plan

| Weeks | Work |
|-------|------|
| 1 | actor attribution + handoff logging + trigger-fact registry (items 1–3) |
| 2–3 | kyc-0003/0004/0005 machine-runnable; family_B db; sanctions/UBO tools |
| 4 | arm harness: D0, D1, D2 (scripted agents first, to unit-test attribution) |
| 5 | LLM simulator on local endpoint; pin model + sampling params |
| 6 | pilot run (320 episodes); cost model; sanity-check that arms differ at all |
| 7 | template expansion to ~100 instances, weighted toward distance ≥2 |
| 8 | full grid; **workshop 4-pager cut here** |
| 9–12 | dispute + suitability tracks, human audit of accidental successes, full paper |

## 8. Kill criteria

State these now, honestly, before the data arrives:

- If the pilot shows **no separation** between D0 and D1/D2 on governed success, the framing
  fails. Fallback: the paper becomes a negative result plus the benchmark artifact
  ("decomposition does not degrade governability, and here is the instrument that shows it") —
  still publishable at a workshop, and honest.
- If separation exists but **fact attenuation does not explain it**, the mechanism claim
  weakens; report the effect without the mechanism and say so.
- If **P1 alone** explains everything, retitle around policy access rather than decomposition.

## 9. Boundary note

The architecture patterns under study (ReAct loops, orchestrator/subagent delegation,
skill-based policy access) are public, generic, and widely documented — that is why they are
studyable here. What stays out: any specific orchestration internals, prompts, routing logic,
evaluation findings, or performance numbers from work systems. The overlap makes this project
more interesting to work on and makes the separation more important to maintain: everything in
this repo derives from public patterns and synthetic tasks only.
