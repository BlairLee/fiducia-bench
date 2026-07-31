"""Model response -> brain action, with failures made explicit.

A parse failure must never be silently scored as a governance failure: "the model
emitted malformed JSON" and "the model declined to escalate" are different findings and
the paper has to be able to tell them apart. So parsing returns a reason on failure and
the brain records it, rather than falling through to a default action.
"""
from __future__ import annotations
import json
from typing import Any

from .schema import DELEGATE, FINISH, HANDOFF


def _message(response: dict[str, Any]) -> dict[str, Any]:
    choices = response.get("choices") or []
    if not choices:
        raise KeyError("response has no choices")
    return choices[0].get("message") or {}


def assistant_message(response: dict[str, Any]) -> dict[str, Any]:
    """The assistant turn to append to the running conversation, verbatim."""
    message = _message(response)
    out: dict[str, Any] = {"role": "assistant",
                           "content": message.get("content") or ""}
    if message.get("tool_calls"):
        out["tool_calls"] = message["tool_calls"]
    return out


def finish_reason(response: dict[str, Any]) -> str:
    choices = response.get("choices") or [{}]
    return str(choices[0].get("finish_reason") or "")


def usage(response: dict[str, Any]) -> tuple[int, int]:
    u = response.get("usage") or {}
    return int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)


def parse_response(response: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Return (action, error). Exactly one is None.

    A tool call becomes a tool/control action; plain content becomes a message. Content
    alongside a tool call is dropped — the call is the act, and letting a component both
    speak and act in one step would make attribution of the utterance ambiguous.
    """
    try:
        message = _message(response)
    except KeyError as e:
        return None, str(e)

    calls = message.get("tool_calls") or []
    if not calls:
        content = (message.get("content") or "").strip()
        if not content:
            return None, "empty response: no tool call and no content"
        return {"message": content}, None

    call = calls[0]
    fn = call.get("function") or {}
    name = fn.get("name")
    if not name:
        return None, "tool call without a function name"

    raw = fn.get("arguments")
    if isinstance(raw, dict):
        args = raw
    else:
        try:
            args = json.loads(raw or "{}")
        except (TypeError, json.JSONDecodeError) as e:
            return None, f"unparseable arguments for {name}: {e}"
    if not isinstance(args, dict):
        return None, f"arguments for {name} are not an object"

    if name == FINISH:
        return {"done": True}, None
    if name == HANDOFF:
        summary = args.get("summary")
        if not isinstance(summary, str):
            return None, "control_handoff without a summary string"
        return {"handoff_payload": summary}, None
    if name == DELEGATE:
        agent, brief = args.get("agent"), args.get("brief", "")
        if not isinstance(agent, str) or not agent:
            return None, "control_delegate without an agent name"
        return {"delegate": agent, "brief": str(brief)}, None

    return {"tool": name, "args": args}, None


def tool_call_id(response: dict[str, Any]) -> str | None:
    calls = _message(response).get("tool_calls") or []
    return calls[0].get("id") if calls else None
