"""Minimal OpenAI-compatible chat client. Stdlib only — no SDK.

Two reasons for writing it by hand. Reproducibility: sampling parameters are pinned in
one place and recorded on every call, so a run can be rerun. And testability: the HTTP
transport is injectable, so the whole harness above it is exercised in tests with canned
responses and never touches a network.
"""
from __future__ import annotations
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol


class Transport(Protocol):
    def post(self, url: str, payload: dict[str, Any],
             headers: dict[str, str]) -> dict[str, Any]: ...


class HttpTransport:
    def __init__(self, timeout: float = 120.0):
        self.timeout = timeout

    def post(self, url: str, payload: dict[str, Any],
             headers: dict[str, str]) -> dict[str, Any]:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **headers}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:                      # surface the body
            raise RuntimeError(f"{e.code} from {url}: "
                               f"{e.read().decode('utf-8', 'replace')[:500]}") from e


@dataclass
class ReplayTransport:
    """Returns canned responses in order. The test double for everything above."""
    responses: list[dict[str, Any]]
    requests: list[dict[str, Any]] = field(default_factory=list)

    def post(self, url: str, payload: dict[str, Any],
             headers: dict[str, str]) -> dict[str, Any]:
        self.requests.append(payload)
        if not self.responses:
            raise AssertionError("ReplayTransport exhausted: model called more times "
                                 "than there are canned responses")
        return self.responses.pop(0)


class LLMClient:
    """One pinned model + sampling configuration.

    `fingerprint()` is what gets published alongside results: anything that changes the
    distribution the episodes were drawn from belongs in it.
    """

    def __init__(self, base_url: str, model: str, api_key: str = "EMPTY",
                 temperature: float = 0.0, top_p: float = 1.0, seed: int | None = 0,
                 max_tokens: int = 1024, transport: Transport | None = None,
                 extra: dict[str, Any] | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.top_p = top_p
        self.seed = seed
        self.max_tokens = max_tokens
        self.extra = extra or {}
        self.transport = transport or HttpTransport()

    def fingerprint(self) -> dict[str, Any]:
        return {"model": self.model, "base_url": self.base_url,
                "temperature": self.temperature, "top_p": self.top_p,
                "seed": self.seed, "max_tokens": self.max_tokens, **self.extra}

    def chat(self, messages: list[dict[str, Any]],
             tools: list[dict[str, Any]] | None = None) -> tuple[dict[str, Any], float]:
        payload: dict[str, Any] = {
            "model": self.model, "messages": messages,
            "temperature": self.temperature, "top_p": self.top_p,
            "max_tokens": self.max_tokens, **self.extra,
        }
        if self.seed is not None:
            payload["seed"] = self.seed
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
            # The harness processes one action per step. Parallel tool calls produce
            # multiple tool_call_ids that must all be answered before the next API call,
            # and the runner has no mechanism for that. Disabling parallel calls keeps
            # the conversation well-formed without changing what the model can do — it
            # just does it sequentially.
            payload["parallel_tool_calls"] = False
        started = time.monotonic()
        response = self.transport.post(
            f"{self.base_url}/chat/completions", payload,
            {"Authorization": f"Bearer {self.api_key}"})
        return response, (time.monotonic() - started) * 1000.0
