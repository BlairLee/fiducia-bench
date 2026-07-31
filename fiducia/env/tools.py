"""Deterministic tools over EnvState. Every call is auto-logged by the environment.

Screening results come from the seed DB (`screening` section), so per-task risk
signals (PEP hits, sanctions fuzzy matches, ...) are data, not code.
"""
from __future__ import annotations
from typing import Any, Callable
from .state import EnvState

ToolFn = Callable[[EnvState, dict[str, Any]], Any]
REGISTRY: dict[str, ToolFn] = {}


def tool(name: str):
    def deco(fn: ToolFn):
        REGISTRY[name] = fn
        return fn
    return deco


def call(state: EnvState, name: str, args: dict[str, Any],
         actor: str = "agent") -> Any:
    if name not in REGISTRY:
        result = {"error": f"unknown tool: {name}"}
    else:
        result = REGISTRY[name](state, args)
    state.log(name, args, result, actor=actor)
    return result


@tool("customer_db.read")
def customer_db_read(state: EnvState, args: dict[str, Any]) -> Any:
    pid = args.get("person_id")
    rec = state.data.get("customers", {}).get(pid)
    return rec if rec is not None else {"error": f"no such person: {pid}"}


@tool("kyc_screening.run")
def kyc_screening_run(state: EnvState, args: dict[str, Any]) -> Any:
    pid = args.get("person_id")
    matches = state.data.get("screening", {}).get(pid, [])
    # Screening a person also discharges the screening obligation for any beneficial
    # owner that resolves to them (a corporate owner resolves to its natural-person UBO).
    for owner in state.data.get("ubo_register", []):
        if owner.get("screen_person_id") == pid:
            owner["screened"] = True
    for m in matches:
        entry = {**m, "person_id": pid, "resolved_false_positive": False}
        # de-dupe on (person_id, list)
        if not any(
            e.get("person_id") == pid and e.get("list") == m.get("list")
            for e in state.data["screening_results"]
        ):
            state.data["screening_results"].append(entry)
    return {"person_id": pid, "matches": matches}


@tool("business_registry.lookup")
def business_registry_lookup(state: EnvState, args: dict[str, Any]) -> Any:
    """Corporate registry lookup by entity id.

    Returns only what a registry actually captures. Beneficial ownership held through
    a corporate vehicle is deliberately absent from the operating company's record —
    it has to be elicited from the customer, and the named vehicle then looked up in
    turn. That two-step is the fact chain kyc-0004 is built around.
    """
    eid = args.get("entity_id")
    rec = state.data.get("business_registry", {}).get(eid)
    if rec is None:
        return {"error": f"no such entity: {eid}"}
    return {"entity_id": eid, **rec}


@tool("doc_request.send")
def doc_request_send(state: EnvState, args: dict[str, Any]) -> Any:
    req = {"person_id": args.get("person_id"), "type": args.get("type")}
    state.data["doc_requests"].append(req)
    return {"sent": True, **req}


@tool("case_mgmt.update")
def case_mgmt_update(state: EnvState, args: dict[str, Any]) -> Any:
    case = state.data["case"]
    if "status" in args:
        case["status"] = args["status"]
    for f in args.get("flags", []):
        if f not in case["flags"]:
            case["flags"].append(f)
    if "note" in args:
        case["notes"].append({"note_type": args.get("note_type", "general"),
                              "note": args["note"]})
    return {"case": case}


@tool("account_open.approve")
def account_open_approve(state: EnvState, args: dict[str, Any]) -> Any:
    state.data["account_open"] = {"status": "approved",
                                  "person_id": args.get("person_id"),
                                  "account_type": args.get("account_type", "checking")}
    return {"status": "approved"}


@tool("escalate")
def escalate(state: EnvState, args: dict[str, Any]) -> Any:
    target = args.get("target", "unspecified")
    state.data["escalations"].append({"target": target, "reason": args.get("reason", "")})
    state.data["case"]["status"] = f"escalated_{target.replace('_team', '')}"
    return {"escalated_to": target}


@tool("policy_lookup.search")
def policy_lookup_search(state: EnvState, args: dict[str, Any]) -> Any:
    q = (args.get("query") or "").lower()
    hits = [r for r in state.data.get("_policy_texts", [])
            if q and q in r["text"].lower()]
    return {"results": hits[:3]}


@tool("transactions.wire_execute")
def transactions_wire_execute(state: EnvState, args: dict[str, Any]) -> Any:
    state.data.setdefault("transactions", {})["wire_status"] = "executed"
    return {"status": "executed", "amount": args.get("amount"),
            "beneficiary": args.get("beneficiary")}


@tool("transactions.freeze")
def transactions_freeze(state: EnvState, args: dict[str, Any]) -> Any:
    state.data.setdefault("transactions", {})["wire_status"] = "frozen"
    return {"status": "frozen"}
