# Contributing to fiducia-bench

Three ways to contribute, ordered by barrier to entry.

## 1. Run episodes (lowest barrier)

You have a GPU and a model that supports function calling. We have tasks. You
contribute compute; the data goes into the paper.

### Setup

```bash
git clone https://github.com/BlairLee/fiducia-bench.git
cd fiducia-bench
pip install -e .
```

### Start a model

Any OpenAI-compatible endpoint works. vLLM example:

```bash
vllm serve <model> \
  --enable-auto-tool-choice --tool-call-parser hermes \
  --max-model-len 16384 --port 8000 --host 0.0.0.0
```

For Qwen3 models, disable thinking mode to keep `<think>` blocks out of the
conversation:

```bash
--extra-json '{"chat_template_kwargs": {"enable_thinking": false}}'
```

### Run a cell

Each cell in the experiment grid is one (task, arm, model, run_id) combination.

```bash
python -m fiducia.cli run-llm \
  --task tasks/seed/kyc-0003.yaml \
  --arm D1 \
  --policy P0 \
  --model <model-id> \
  --max-steps 25 \
  --run-id <your-name>-r1
```

Arms: `D0` (single loop), `D1` (fixed pipeline), `D2` (orchestrator + subagents).
Policy: `P0` (full policy in context), `P1` (policy via tool lookup).

### What to submit

Two files per episode from `results/`:

- `*.json` — the trajectory (turns, tool calls, handoffs, audit log)
- `*.verdict.json` — the verdict (governed_success, violations, decomposition report)

Open a PR with these files under `results/contributed/<your-name>/`, or email them.

### Requirements (non-negotiable)

These ensure episodes are comparable across contributors:

| Parameter | Value | Why |
|-----------|-------|-----|
| `temperature` | 0.0 | Reproducibility |
| `seed` | 0 | Reproducibility |
| `max_tokens` | 1024 | Consistent generation budget |
| `max_steps` | 25 | Consistent episode budget |
| Qwen3 thinking | disabled | Prevents `<think>` in content |

If your endpoint does not support `seed`, note it in the PR description. If you
use a quantized model, record the quantization method (GPTQ-Int4, AWQ, etc.) —
it lands in `model_fingerprint` automatically.

### Models we need data from

Priority order (highest first):

1. **Qwen3-30B-A3B** (GPTQ-Int4 or AWQ) — our current best local model
2. **Llama-3.1-70B-Instruct** — different model family, tests generality
3. **Qwen3-72B** or **Qwen3-235B-A22B** — upper capability bound
4. **GPT-4o / Claude** via API — ceiling reference (note: costs real money)
5. **Qwen3-8B** — floor reference (we have this data already)

### Quick validation

Before submitting, verify the trajectory is well-formed:

```bash
python -c "
from fiducia.runner import load_task
from fiducia.schema import Trajectory
import json

traj = Trajectory.model_validate(json.load(open('results/<your-file>.json')))
print(f'turns: {len(traj.turns)}, tool_calls: {sum(len(t.tool_calls) for t in traj.turns)}')
print(f'arm: {traj.arm}, truncated: {traj.truncated}')
print(f'llm_calls: {len(traj.llm_calls)}, parse_errors: {sum(1 for c in traj.llm_calls if c.parse_error)}')
print(f'model: {traj.model_fingerprint.get(\"model\", \"unknown\")}')
"
```

---

## 2. Write variant tasks (medium barrier)

Expand the task corpus by adding variation axes to the template generator, or by
writing new seed tasks.

### Adding variation axes to existing seeds

The generator lives in `fiducia/expand.py`. Each seed has a builder function
(`_build_kyc000N_variants`) that defines what varies. To add a new axis:

1. Read the seed task YAML and its DB to understand the scenario
2. Identify a data field whose value flips the ground truth
3. Add the variation to the builder, including updated `expected` and `trigger_facts`
4. Add a test to `tests/test_expand.py` that verifies the flip

Example: kyc-0004 varies UBO stake percentage. At 30% the UBO must be screened
(KYC-06 fires). At 20% it must not. The generator produces both variants from the
same seed.

### Writing a new seed task

A seed task is a hand-written scenario that exercises a specific policy rule or
governance pattern. It must satisfy all of the following:

#### Checklist

```
- [ ] Task YAML in tasks/seed/ with simulator, trigger_facts, expected
- [ ] Seed DB in envs/db/ with synthetic data
- [ ] Policy rule(s) in envs/policies/kyc_v1.yaml (if new)
- [ ] Oracle script: governed_success=True
- [ ] At least one trap script: governed_success=False
- [ ] Oracle and trap have DIFFERENT violation signatures
- [ ] constraint_distance declared correctly
- [ ] Each trigger_fact declares exactly one of obliges/forbids
- [ ] Tests in tests/test_e2e.py verifying oracle/trap separation
```

#### Verify locally

```bash
# Oracle must pass
python -m fiducia.cli run --task tasks/seed/<your-task>.yaml --script oracle
# => governed_success: true

# Trap must fail
python -m fiducia.cli run --task tasks/seed/<your-task>.yaml --script naive
# => governed_success: false

# All tests must pass
python tests/test_e2e.py
```

#### Design constraints

- **Everything synthetic.** No real entities, regulations, or jurisdictions. Rules
  are *inspired by* public guidance, not copied from it.
- **Never** add tasks involving people search, relationship graphs, warm-intro
  paths, or professional-network navigation. See CLAUDE.md "Hard boundary".
- **Traps are the point.** The trap script must satisfy the user's surface goal
  while violating policy. A trap that obviously fails capability is not useful.
- **Prefer `constraint_distance >= 2`.** The headline figure needs data points
  where the trigger fact must cross multiple boundaries. Distance-0 control tasks
  are useful but we have enough of those.

---

## 3. Improve the harness (highest barrier)

### Open work items

From CLAUDE.md "Smaller, open":

- **Judge for soft rules.** KYC-07 (did the agent explain clearly to the customer)
  needs an LLM judge. Must be calibrated against human labels with agreement
  reported. The ≥70% deterministic check target is currently met only because
  soft rules do not exist.
- **P1 grid episodes.** D0×P1 vs D0×P0 isolates policy visibility from
  decomposition. The prompt and tool are verified end-to-end, but no real model
  episodes exist.

### Design invariants (do not break these)

1. The environment owns the audit log and actor attribution
2. Verification replays the trajectory against a fresh environment
3. Prefer deterministic checks (≥70%)
4. Every metric is a pure function of (trajectory + task YAML)
5. Every task carries an oracle script and a trap script
6. Traps are the point — escalation is scored in both directions
7. Where an agent asserts a judgement, the environment re-derives it
8. The topology assigns identity and context; the component never does

### Running tests

```bash
python tests/test_e2e.py      # 34 tests — tasks + verifiers
python tests/test_arms.py     # 13 tests — orchestration mechanics
python tests/test_llm.py      # 28 tests — LLM brain + prompts + P1
python tests/test_expand.py   # 23 tests — template expansion
```

All tests are hermetic (no network, no GPU, no model endpoint).

---

## Code of conduct

This is a research project. Contributions are credited in the paper acknowledgements.
Be honest about what your data shows — a negative result is more valuable than a
manufactured positive one.
