"""Tool schemas handed to the model: environment tools plus control tools.

Environment tools come from `env.tools.SPECS`, so what the model sees is generated from
the same declaration the environment executes — a tool cannot be described to the model
in terms that differ from what it does.

Control tools are how a component expresses the parts of the brain protocol that are not
tool calls: handing off, delegating, finishing. Which ones exist is decided by the
component's place in the topology, never by the component.
"""
from __future__ import annotations
from typing import Any

from ...env.tools import SPECS, ToolDoc

CONTROL_PREFIX = "control_"
FINISH = f"{CONTROL_PREFIX}finish"
HANDOFF = f"{CONTROL_PREFIX}handoff"
DELEGATE = f"{CONTROL_PREFIX}delegate"

_JSON_TYPES = {"string": "string", "number": "number", "integer": "integer",
               "boolean": "boolean", "array": "array", "object": "object"}


def _property(spec: str) -> dict[str, Any]:
    """Parse a "type: description" arg declaration into a JSON-schema property."""
    kind, _, description = spec.partition(":")
    kind = kind.strip().lower()
    prop: dict[str, Any] = {"type": _JSON_TYPES.get(kind, "string"),
                            "description": description.strip()}
    if prop["type"] == "array":
        prop["items"] = {"type": "string"}
    return prop


def function_schema(doc: ToolDoc) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": doc.name,
            "description": doc.description,
            "parameters": {
                "type": "object",
                "properties": {k: _property(v) for k, v in doc.args.items()},
                "required": list(doc.required),
            },
        },
    }


def environment_tools(names: list[str]) -> list[dict[str, Any]]:
    """Schemas for the named tools, in the order given. Unknown names are skipped —
    a task may list a tool the registry does not implement, and the model should not
    be offered something that cannot be called."""
    return [function_schema(SPECS[n]) for n in names if n in SPECS]


def _control(name: str, description: str, properties: dict[str, Any],
             required: list[str]) -> dict[str, Any]:
    return {"type": "function",
            "function": {"name": name, "description": description,
                         "parameters": {"type": "object", "properties": properties,
                                        "required": required}}}


def control_tools(*, can_handoff: bool = False,
                  delegates: list[str] | None = None) -> list[dict[str, Any]]:
    tools = [_control(FINISH, "Finish: there is nothing further for you to do.", {}, [])]
    if can_handoff:
        tools.append(_control(
            HANDOFF,
            "Pass your work to the next stage. Everything you want the next stage to "
            "know must be in the summary — it cannot see your tool results.",
            {"summary": {"type": "string",
                         "description": "what the next stage receives"}},
            ["summary"]))
    if delegates:
        tools.append(_control(
            DELEGATE,
            "Assign work to one of your subagents and wait for its report.",
            {"agent": {"type": "string", "enum": list(delegates),
                       "description": "which subagent to assign to"},
             "brief": {"type": "string", "description": "instructions for it"}},
            ["agent", "brief"]))
    return tools


def tools_for(component_tools: list[str], *, can_handoff: bool = False,
              delegates: list[str] | None = None) -> list[dict[str, Any]]:
    return environment_tools(component_tools) + control_tools(
        can_handoff=can_handoff, delegates=delegates)
