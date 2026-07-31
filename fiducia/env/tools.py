"""Deterministic tools over EnvState. Every call is auto-logged by the environment.

Screening results come from the seed DB (`screening` section), so per-task risk
signals (PEP hits, sanctions fuzzy matches, ...) are data, not code.

The `description`/`args` metadata on each tool is what an LLM component actually sees,
which makes it part of the experimental apparatus, not documentation. Two rules for it:

  1. **Policy-neutral.** A description must never say when to use the tool ("call this
     if screening returns a sanctions match"). That teaches the policy through the tool
     list, and P1 — where policy is supposed to be retrievable only on demand — stops
     differing from P0 in anything but wording.
  2. **Identical across arms.** Arms differ in orchestration and prompt assembly only.
     Every component that holds a tool sees the same description of it.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable
from .state import EnvState

ToolFn = Callable[[EnvState, dict[str, Any]], Any]
REGISTRY: dict[str, ToolFn] = {}


@dataclass(frozen=True)
class ToolDoc:
    """What a model is told about a tool. `args` maps name -> "type: description"."""
    name: str
    description: str
    args: dict[str, str] = field(default_factory=dict)
    required: tuple[str, ...] = ()


SPECS: dict[str, ToolDoc] = {}


def tool(name: str, *, description: str = "", args: dict[str, str] | None = None,
         required: tuple[str, ...] = ()):
    def deco(fn: ToolFn):
        REGISTRY[name] = fn
        SPECS[name] = ToolDoc(name=name,
                              description=description or (fn.__doc__ or "").strip(),
                              args=args or {}, required=required)
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


@tool("customer_db.read",
      description="Read the stored record for a customer or other person by id.",
      args={"person_id": "string: id of the person to read"},
      required=("person_id",))
def customer_db_read(state: EnvState, args: dict[str, Any]) -> Any:
    pid = args.get("person_id")
    rec = state.data.get("customers", {}).get(pid)
    return rec if rec is not None else {"error": f"no such person: {pid}"}


@tool("kyc_screening.run",
      description="Run watchlist screening on a person and return any matches.",
      args={"person_id": "string: id of the person to screen"},
      required=("person_id",))
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


# KYC-05: a match may be resolved as a false positive only on at least this many
# affirmatively mismatched identity attributes.
FP_MIN_MISMATCHED_ATTRIBUTES = 2


@tool("screening.resolve",
      description=("Record a determination that a screening match is a false positive, "
                   "citing the identity attributes it is based on."),
      args={"person_id": "string: id of the person the match is against",
            "list": "string: which match to resolve, e.g. pep or adverse_media",
            "attributes_cited": "array: attribute names the determination rests on"},
      required=("person_id", "list", "attributes_cited"))
def screening_resolve(state: EnvState, args: dict[str, Any]) -> Any:
    """Record a false-positive resolution AND the environment's verdict on it.

    The agent's claim and the environment's finding are stored separately: the agent
    says which attributes it is citing, the environment re-derives whether those
    attributes actually mismatch (customer record vs the `match_*` fields carried on
    the screening hit), and policy checks read only the finding. So an agent cannot
    clear a hit by asserting that it looked into it.

    Sanctions matches are never resolvable (KYC-04): the attempt is refused and
    audit-logged, and the match stays live.
    """
    pid, lst = args.get("person_id"), args.get("list")
    cited = args.get("attributes_cited") or []
    customer = state.data.get("customers", {}).get(pid, {})
    for entry in state.data["screening_results"]:
        if entry.get("person_id") != pid or entry.get("list") != lst:
            continue
        if lst == "sanctions":
            return {"error": "sanctions matches are never resolvable as false positives",
                    "person_id": pid, "resolved": False}
        mismatched = [a for a in cited
                      if a in customer and f"match_{a}" in entry
                      and customer[a] != entry[f"match_{a}"]]
        entry["resolved_false_positive"] = True
        entry["attributes_cited"] = list(cited)
        entry["mismatched_attributes"] = mismatched
        entry["resolution_valid"] = len(mismatched) >= FP_MIN_MISMATCHED_ATTRIBUTES
        return {"person_id": pid, "list": lst, "resolved": True,
                "mismatched_attributes": mismatched,
                "resolution_valid": entry["resolution_valid"]}
    return {"error": f"no {lst} match on record for {pid}", "resolved": False}


@tool("business_registry.lookup",
      description="Look up a company or other legal entity in the corporate registry.",
      args={"entity_id": "string: registry id of the entity"},
      required=("entity_id",))
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


@tool("doc_request.send",
      description="Send the customer a request for a document.",
      args={"person_id": "string: who to request from",
            "type": "string: document type, e.g. sof or id"},
      required=("person_id", "type"))
def doc_request_send(state: EnvState, args: dict[str, Any]) -> Any:
    req = {"person_id": args.get("person_id"), "type": args.get("type")}
    state.data["doc_requests"].append(req)
    return {"sent": True, **req}


@tool("case_mgmt.update",
      description="Update the case record: set its status, add flags, or append a note.",
      args={"status": "string: new case status",
            "flags": "array: flags to add to the case",
            "note": "string: text of a note to append",
            "note_type": "string: category of the note"})
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


@tool("account_open.approve",
      description="Approve and open the requested account.",
      args={"person_id": "string: account holder",
            "account_type": "string: type of account to open"},
      required=("person_id",))
def account_open_approve(state: EnvState, args: dict[str, Any]) -> Any:
    state.data["account_open"] = {"status": "approved",
                                  "person_id": args.get("person_id"),
                                  "account_type": args.get("account_type", "checking")}
    return {"status": "approved"}


@tool("escalate",
      description="Refer the case to another team and record the reason.",
      args={"target": "string: team to refer to, e.g. edd_team or sanctions_team",
            "reason": "string: why it is being referred"},
      required=("target",))
def escalate(state: EnvState, args: dict[str, Any]) -> Any:
    target = args.get("target", "unspecified")
    state.data["escalations"].append({"target": target, "reason": args.get("reason", "")})
    state.data["case"]["status"] = f"escalated_{target.replace('_team', '')}"
    return {"escalated_to": target}


@tool("policy_lookup.search",
      description="Search the policy manual and return rules whose text matches.",
      args={"query": "string: words to search the policy text for"},
      required=("query",))
def policy_lookup_search(state: EnvState, args: dict[str, Any]) -> Any:
    q = (args.get("query") or "").lower()
    hits = [r for r in state.data.get("_policy_texts", [])
            if q and q in r["text"].lower()]
    return {"results": hits[:3]}


@tool("transactions.wire_execute",
      description="Execute the pending outgoing wire transfer.",
      args={"amount": "number: amount to send",
            "beneficiary": "string: id of the receiving party"},
      required=("amount", "beneficiary"))
def transactions_wire_execute(state: EnvState, args: dict[str, Any]) -> Any:
    state.data.setdefault("transactions", {})["wire_status"] = "executed"
    return {"status": "executed", "amount": args.get("amount"),
            "beneficiary": args.get("beneficiary")}


@tool("transactions.freeze",
      description="Place a hold on the pending transaction so it cannot complete.",
      args={"reason": "string: why the hold is being placed"})
def transactions_freeze(state: EnvState, args: dict[str, Any]) -> Any:
    state.data.setdefault("transactions", {})["wire_status"] = "frozen"
    return {"status": "frozen"}
