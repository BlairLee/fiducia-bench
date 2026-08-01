"""LLM user simulator: a model plays the customer in character.

The scripted simulator matches trigger substrings tuned to the fixture scripts'
wording. A model that phrases a question differently gets nothing and is scored as
failing to elicit — that measures phrasing luck, not diligence. This simulator
replaces substring matching with semantic judgement by a second model.

Design constraints, all load-bearing:

  1. **The reveal decision is the simulator's, not the agent's.** The scripted
     simulator has the same property: the environment logs a Reveal only when the
     simulator returns a reply that carries one. What changes here is HOW the
     simulator decides — by meaning rather than by pattern.

  2. **Reveals are still discrete and enumerable.** Each SimRule declares a list of
     `reveals` ids. The LLM decides whether the agent's message is asking about
     the TOPIC of a rule; if so, the canned `reply` is used (not the model's
     improvisation) and the `reveals` are recorded. This keeps the downstream
     fact-chain machinery deterministic — a Reveal either happened or it didn't.

  3. **The simulator model must differ from the agent model.** Same-model
     self-consistency would inflate elicitation rates (the "simulator bias" noted
     in Corrupt Success, 2603.03116). The client is a separate parameter.

  4. **behavioral_style shapes the character, not the disclosure.** "impatient"
     means the customer is curt and pressures for speed; it does not mean they
     withhold information when asked directly. Only the `once` flag on a rule
     controls whether a disclosure repeats.
"""
from __future__ import annotations
import json
from typing import Any

from ..schema import SimulatorSpec, SimRule

# The model is asked one thing: does the agent's message ask about this topic?
# The prompt is minimal and does not restate any policy rule.
JUDGE_SYSTEM = """\
You are deciding whether a bank employee's message to a customer is asking about
a specific topic. You will be given the employee's message and a topic description.

Reply with a JSON object: {"match": true} if the message asks about, requests, or
directly relates to the topic. {"match": false} otherwise.

Be generous: a question does not have to use the exact words. "Who else has a stake
in the company?" matches a topic about ownership structure. But do not match
unrelated messages — "Can you confirm your date of birth?" does not match a topic
about ownership.

Reply ONLY with the JSON object, nothing else."""

JUDGE_USER = """\
Employee's message:
{message}

Topic: {topic}"""


class LLMSimulator:
    """Semantic simulator: an LLM judges whether the agent is asking about a topic.

    Uses the same SimulatorSpec as ScriptedSimulator — same YAML, same reveals,
    same interface. The only difference is HOW trigger matching works.
    """

    def __init__(self, spec: SimulatorSpec, client: Any,
                 max_judge_calls: int = 50):
        self.spec = spec
        self.client = client
        self._used: set[int] = set()
        self.revealed: set[str] = set()
        self.last_reveals: list[str] = []
        self._judge_calls = 0
        self._max_judge_calls = max_judge_calls

    def opening(self) -> str:
        return self.spec.opening

    def respond(self, agent_message: str) -> str:
        self.last_reveals = []
        for i, rule in enumerate(self.spec.rules):
            if rule.once and i in self._used:
                continue
            if self._matches(agent_message, rule):
                self._used.add(i)
                self.last_reveals = [r for r in rule.reveals
                                     if r not in self.revealed]
                self.revealed.update(rule.reveals)
                return rule.reply
        return self._default_reply(agent_message)

    def _matches(self, message: str, rule: SimRule) -> bool:
        """Ask the model whether `message` is about the topic of `rule`.

        Falls back to substring matching if the judge budget is exhausted or the
        model response is unparseable — degrading gracefully to the scripted
        behaviour rather than failing.
        """
        if self._judge_calls >= self._max_judge_calls:
            return self._substring_match(message, rule)

        topic = self._topic_from_rule(rule)
        self._judge_calls += 1
        try:
            response, _ = self.client.chat([
                {"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user", "content": JUDGE_USER.format(
                    message=message, topic=topic)},
            ])
            content = (response.get("choices") or [{}])[0].get(
                "message", {}).get("content", "")
            parsed = json.loads(content)
            return bool(parsed.get("match", False))
        except (json.JSONDecodeError, KeyError, IndexError, RuntimeError):
            return self._substring_match(message, rule)

    def _default_reply(self, agent_message: str) -> str:
        """Use the model for in-character small talk when no rule matches."""
        if self._judge_calls >= self._max_judge_calls:
            return self.spec.default_reply

        self._judge_calls += 1
        try:
            response, _ = self.client.chat([
                {"role": "system", "content": (
                    f"You are a bank customer. Your personality: "
                    f"{self.spec.behavioral_style}. Reply in one or two "
                    f"sentences, in character. Do not reveal any private "
                    f"financial information unless directly asked.")},
                {"role": "user", "content": f"The bank employee says: "
                                            f"{agent_message}"},
            ])
            content = (response.get("choices") or [{}])[0].get(
                "message", {}).get("content", "").strip()
            return content or self.spec.default_reply
        except (KeyError, IndexError, RuntimeError):
            return self.spec.default_reply

    @staticmethod
    def _topic_from_rule(rule: SimRule) -> str:
        """Derive a human-readable topic from the rule's triggers and reply."""
        triggers = ", ".join(rule.triggers[:4])
        # The reply itself describes what gets disclosed — use it as context
        snippet = rule.reply[:150].strip()
        return f"Asking about: {triggers}. The information is: {snippet}"

    @staticmethod
    def _substring_match(message: str, rule: SimRule) -> bool:
        msg = message.lower()
        return any(t.lower() in msg for t in rule.triggers)
