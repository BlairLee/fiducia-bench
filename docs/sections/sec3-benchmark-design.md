<!-- Section 3: Benchmark Design -->
<!-- Target: ~1.5 pages in NeurIPS format -->
<!-- Style: present tense, "we" throughout, no repo URLs (double-blind) -->

## 3. Benchmark Design

Fiducia-bench is an environment for measuring the *governability* of financial
agents --- whether they comply with policy, escalate when obligated, abstain
when required, and leave an auditable trail. The design is driven by three
principles: (i) the environment, not the agent, owns the audit log and all
attribution; (ii) verification replays the trajectory against the environment's
state history, so rule triggers evaluate conditions as they were at each step,
not the final state; and (iii) at least 70\% of policy rules are checkable
deterministically, without a judge.

### 3.1 Environment and Tools

Each episode begins with a seeded JSON database representing a synthetic
financial institution's records: customer profiles, screening results,
corporate registries, and transaction state. All entities, jurisdictions, and
policy rules are invented; nothing here constitutes legal or compliance advice.

The agent interacts with the environment through a fixed set of deterministic
tools (e.g., \texttt{customer\_db.read}, \texttt{kyc\_screening.run},
\texttt{escalate}, \texttt{account\_open.approve}). Each tool call mutates the
environment state and is recorded in an **environment-owned audit log** with a
monotonic sequence number, the tool name, arguments, result, and the actor who
issued it. The actor is stamped by the *topology*, never by the component
itself --- a model that emits \texttt{\{"actor": "compliance\_officer"\}} in
its output changes nothing in the log. This is the same principle as the
environment owning the audit log, applied one level up: attribution is a
property of the architecture, not a claim by the component.

### 3.2 Policy Packs

Policy rules are machine-readable YAML artifacts. Each rule declares a
severity, a natural-language text (for the agent's context under P0 and for
the paper's appendix), and a **check type** that determines how the verifier
evaluates it:

- \textbf{\texttt{require\_before}}: action $A$ must be preceded by action $B$
  (e.g., screening must precede approval).
- \textbf{\texttt{allow\_list}}: only the listed tools may be called; any
  other tool call is a violation.
- \textbf{\texttt{state\_assert}}: a condition on the environment state must
  hold at episode end (e.g., wire status is ``frozen'').
- \textbf{\texttt{forbid\_when}}: action $A$ is forbidden while a state
  condition holds (e.g., approving an account while an unscreened >25\% owner
  exists).

Verification proceeds by **replaying** the trajectory: the verifier
reconstructs the environment state at each tool call and evaluates the
applicable rules against that state. This prevents a common failure mode in
post-hoc evaluation where the agent's final action retroactively satisfies a
rule that was violated mid-episode.

The current policy pack contains 10 rules across KYC, sanctions, and
beneficial-ownership domains. Of these, 10/10 (100\%) are checked
deterministically. The $\geq$70\% target allows room for judge-evaluated soft
rules (e.g., ``did the agent explain the hold to the customer in plain
language?'') which are designed but not yet implemented.

### 3.3 Tasks and Trigger Facts

Each task is a YAML file specifying a scenario, a customer simulator, expected
terminal state, required and forbidden actions, and **trigger facts** --- the
policy-relevant information whose journey through the system is the object of
measurement.

A trigger fact declares:
\begin{itemize}
  \item \texttt{discovered\_by}: which tool call or customer disclosure
    surfaces the fact.
  \item \texttt{obliges} or \texttt{forbids}: the action the fact mandates or
    prohibits (exactly one; a fact cannot do both).
  \item \texttt{present\_in}: tokens whose presence in a handoff payload
    indicates the fact survived the boundary.
  \item \texttt{depends\_on}: for chained obligations, the upstream fact that
    must be carried first.
\end{itemize}

\noindent The five seed tasks span constraint distance 0--2:

\begin{table}[h]
\centering
\small
\begin{tabular}{llcll}
\toprule
Task & Scenario & Dist. & Obligation & Key property \\
\midrule
0001 & Clean account opening & 0 & Negative & Escalation-precision control \\
0002 & Source-of-funds elicitation & 1 & Positive & Fact crosses one boundary \\
0003 & Sanctions match on wire & 2 & Positive & Freeze + escalate \\
0004 & Hidden UBO, chained facts & 2 & Positive & Two-link fact chain \\
0005 & Resolvable PEP false positive & 2 & Negative & Mirror of 0004 \\
\bottomrule
\end{tabular}
\caption{Seed tasks. Constraint distance = number of component boundaries the
trigger fact must cross between discovery and obligated action. Tasks 0004 and
0005 are a paired mirror: the same mechanism (summarization drops a fact at the
boundary) produces under-escalation in 0004 and over-escalation in 0005.}
\label{tab:tasks}
\end{table}

Each task carries an **oracle** script (governed\_success = true) and at least
one **trap** script (governed\_success = false). The trap satisfies the user's
surface goal while violating policy --- it is the task's unit test. Escalation
is scored in both directions: over-escalating a clean case (0001, 0005) is a
failure, not a conservative success.

Where an agent asserts a judgement (e.g., ``this PEP match is a false
positive''), the environment **re-derives** the conclusion by comparing the
agent's cited attributes against the database records. Policy rules read only
the environment's finding, never the agent's claim. This prevents a model from
clearing a screening hit by simply asserting that it looked into it.

### 3.4 Simulator

The customer is played by a simulator that responds to the agent's messages.
Two implementations share the same interface and the same YAML rule
definitions:

\textbf{Scripted simulator.} Each rule declares trigger substrings; if the
agent's message contains one, the canned reply is returned and the associated
\texttt{reveals} are recorded as environment-owned \texttt{Reveal} events.
Deterministic and reproducible, but measures phrasing luck: a model that asks
``who else has a stake?'' instead of ``beneficial owner'' receives no
disclosure.

\textbf{LLM simulator.} A second model acts as a binary topic-judge: given the
agent's message and a rule's topic, does the message ask about it? If yes, the
same canned reply and reveals are used --- the downstream fact-chain machinery
stays deterministic. The simulator model differs from the agent model to avoid
self-consistency bias. Falls back to substring matching when the judge budget
is exhausted.

### 3.5 Arms: the Independent Variable

The independent variable is the agent's **decomposition topology**. Three arms
are implemented, sharing identical tools, policy corpus, and behavioral prompt
(ROLE + CONDUCT). What differs is only the topology and the context each
component receives.

\begin{table}[h]
\centering
\small
\begin{tabular}{lll}
\toprule
Arm & Architecture & Context isolation \\
\midrule
D0 & Single ReAct loop & None (one context) \\
D1 & Fixed pipeline: intake $\to$ research $\to$ decide &
     Each stage sees only the previous stage's handoff payload \\
D2 & Orchestrator + scoped subagents &
     Subagent sees its brief; orchestrator sees only the report \\
\bottomrule
\end{tabular}
\caption{Decomposition arms. A brain (the component under test) is separated
from the arm (the topology). Swapping a scripted brain for an LLM brain
changes nothing about attribution, context isolation, or tool scoping.}
\label{tab:arms}
\end{table}

A \textbf{brain} decides what to do next; an \textbf{arm} decides who exists,
what each component can see, what crosses the boundaries between them, and who
gets attributed for each call. The brain's output is filtered to a whitelist
of allowed keys (tool, args, message, handoff\_payload, done); anything else
--- \texttt{actor} above all --- is discarded before the action reaches the
runner.

\textbf{Factor P} (policy access) is orthogonal: under P0, the full policy
text is pasted into every component's system prompt; under P1, it is available
only through \texttt{policy\_lookup.search}. Both modes access the identical
corpus, verified end-to-end in the test suite.
