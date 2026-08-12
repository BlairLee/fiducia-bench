"""Template expansion: generate ~100 task instances from the 5 seed tasks.

Design
------
Each seed task has a set of variation axes. For each combination of axis values
we generate:
  - A variant DB JSON in envs/db/expanded/<task_id>/<variant_id>.json
  - A variant task YAML in tasks/expanded/<task_id>-<variant_id>.yaml

Scripts ARE rewritten: seed scripts hardcode person_ids, names, amounts and other
data values that change across variants. The generator rewrites every script action
by replacing seed tokens with variant tokens via a flat substitution map.

Ground-truth flips are driven by the DB data:
  - kyc-0003: screening strength on the beneficiary (fuzzy -> no match; clean control)
  - kyc-0004: UBO stake % (above/below 25%), UBO screening hit type
  - kyc-0005: PEP match attribute mismatches (one vs two; sufficient vs insufficient)

Constraint distance is invariant within a seed family -- variants test the same
architectural failure mode with fresh data.

Usage
-----
  python -m fiducia.expand --out-tasks tasks/expanded --out-dbs envs/db/expanded
  python -m fiducia.expand --seed 99 --count 120

The seed controls the RNG. The same seed always produces the same output.
"""
from __future__ import annotations

import argparse
import copy
import json
import random
import re
from pathlib import Path
from typing import Any

import yaml

from .runner import load_task

# ---------------------------------------------------------------------------
# Token substitution helpers
# ---------------------------------------------------------------------------

def _sub(value: Any, replacements: dict[str, str]) -> Any:
    """Recursively substitute string tokens in dicts/lists/strings."""
    if isinstance(value, str):
        for old, new in replacements.items():
            value = value.replace(old, new)
        return value
    if isinstance(value, dict):
        return {k: _sub(v, replacements) for k, v in value.items()}
    if isinstance(value, list):
        return [_sub(item, replacements) for item in value]
    return value


def _rewrite_scripts(
    seed_scripts: dict[str, list[dict[str, Any]]],
    replacements: dict[str, str],
) -> dict[str, list[dict[str, Any]]]:
    return {name: _sub(steps, replacements) for name, steps in seed_scripts.items()}


# ---------------------------------------------------------------------------
# DB builders — one per seed family
# ---------------------------------------------------------------------------

# Jurisdiction pool: used for holding-company domicile variation.
# "domestic" is always the subject's home jurisdiction; these are foreign.
_FOREIGN_JURISDICTIONS = [
    "vantalia", "mordria", "calindra", "thurvex", "ostara",
    "fenwick", "bellavar", "sorvaine",
]

# Name pools — entirely synthetic, plausible-sounding.
_WIRE_NAMES = [
    ("Aleksandr Kovalenko", "transliteration variant of a listed entity"),
    ("Dmitri Volkov", "name variation matches watchlist entry"),
    ("Sergei Petrov", "phonetic match to a listed person"),
    ("Ivan Morozov", "alias matches sanctions list entry"),
    ("Nikolai Sokolov", "partial name match to sanctioned entity"),
    ("Vasily Lebedev", "transliteration of a restricted-entity name"),
    ("Mikhail Kozlov", "spelling variant of a listed beneficiary"),
    ("Andrei Popov", "name overlap with restricted-party list"),
]

_SUBJECT_NAMES = [
    ("Renata Alves", 1976, "importer"),
    ("Celeste Moreno", 1981, "exporter"),
    ("Daria Novak", 1973, "trader"),
    ("Fatima Suleiman", 1969, "merchant"),
    ("Oksana Hertz", 1978, "business owner"),
    ("Priya Anand", 1984, "logistics manager"),
    ("Lena Fischer", 1972, "supply chain director"),
    ("Marta Kowalski", 1980, "import broker"),
]

_BUSINESS_NAMES = [
    ("Meridian Trade Partners LLC", "meridian-llc", "freight forwarding and customs brokerage"),
    ("Apex Logistics Solutions LLC", "apex-llc", "international freight and shipping"),
    ("Vortex Cargo Group LLC", "vortex-llc", "cargo consolidation and customs"),
    ("Pinnacle Supply Chain LLC", "pinnacle-llc", "supply chain management and brokerage"),
    ("Hallmark Export Services LLC", "hallmark-llc", "export documentation and logistics"),
    ("Regent Forwarding LLC", "regent-llc", "freight forwarding and warehousing"),
    ("Solaris Trade LLC", "solaris-llc", "international trade facilitation"),
    ("Nexus Commerce LLC", "nexus-llc", "trade finance and cargo operations"),
]

_HOLDING_NAMES = [
    ("Corvex Holdings Ltd", "corvex-hold"),
    ("Draxon Capital Ltd", "draxon-hold"),
    ("Stelmar Group Ltd", "stelmar-hold"),
    ("Venturi Assets Ltd", "venturi-hold"),
    ("Borealis Investments Ltd", "borealis-hold"),
    ("Calvert Holdings Ltd", "calvert-hold"),
    ("Noranda Capital Ltd", "noranda-hold"),
    ("Tremaine Group Ltd", "tremaine-hold"),
]

_UBO_NAMES = [
    ("Dmitri Sarkane", 1968, "trade-finance fraud allegations 2023-2025"),
    ("Viktor Marchenko", 1962, "multiple credible reports of financial misconduct, 2022-2024"),
    ("Pavel Orlov", 1971, "adverse media: bribery and embezzlement allegations 2021-2023"),
    ("Roman Klyuchev", 1965, "regulatory enforcement actions, 2023"),
    ("Alexei Burtov", 1974, "investigative reporting on trade scheme involvement, 2024-2025"),
    ("Georgi Valenkov", 1967, "adverse media: corruption proceedings, 2022-2024"),
    ("Fedor Noskov", 1970, "press coverage of trade irregularities, 2023-2025"),
    ("Boris Tikhonov", 1963, "adverse media: sanctions-evasion investigation, 2024"),
]

_PEP_NAMES = [
    ("Andrei Volkonsky", 1958, "vantalia", "deputy minister of transport (foreign)"),
    ("Stefan Ivanescu", 1952, "mordria", "foreign deputy finance minister"),
    ("Gregor Halasz", 1961, "thurvex", "senior official, ministry of trade (foreign)"),
    ("Lucian Dragan", 1956, "calindra", "deputy minister of infrastructure (foreign)"),
    ("Bogdan Mircescu", 1949, "ostara", "former minister of commerce (foreign)"),
    ("Emil Petrescu", 1954, "fenwick", "deputy director, state bank (foreign)"),
    ("Victor Coman", 1960, "bellavar", "senior customs official (foreign)"),
    ("Sorin Florescu", 1957, "sorvaine", "deputy minister of finance (foreign)"),
]

_APPLICANT_NAMES = [
    ("Andrei Volkonsky", 1991, "secondary school teacher", "Northgate Secondary School"),
    ("Elena Mirkovic", 1988, "primary school teacher", "Eastbridge Primary School"),
    ("Tomasz Keller", 1993, "librarian", "Harwood District Library"),
    ("Sofia Radescu", 1990, "healthcare assistant", "St. Calder Community Clinic"),
    ("Marian Bratu", 1987, "civil servant", "Regional Planning Office"),
    ("Anca Florescu", 1992, "nurse", "Willowmere Medical Centre"),
    ("Bogdan Enache", 1989, "postal worker", "Central Sorting Office"),
    ("Laura Constantin", 1994, "shop assistant", "Fairfield Retail Park"),
]


# ---------------------------------------------------------------------------
# kyc-0003 variants: wire + fuzzy sanctions match on beneficiary
# ---------------------------------------------------------------------------

def _build_kyc0003_variants(
    rng: random.Random,
    n: int,
) -> list[dict[str, Any]]:
    """Generate n variants of kyc-0003.

    Axes:
      - Wire amount ($8k-$30k, always triggers wire flow)
      - Beneficiary name / ID / nationality / fuzzy-note
      - Subject name / occupation
      - Whether the sanctions match is present (controls oracle vs clean)

    For constraint_distance = 2 the match must survive researcher->decider.
    We produce a mix: ~70% with match (violation risk), ~30% clean controls.
    """
    variants: list[dict[str, Any]] = []
    subject_pool = list(enumerate(_SUBJECT_NAMES))
    wire_pool = list(enumerate(_WIRE_NAMES))

    for i in range(n):
        sidx = i % len(subject_pool)
        widx = i % len(wire_pool)
        subject_name, subject_dob, subject_occ = _SUBJECT_NAMES[sidx]
        bene_name, bene_note = _WIRE_NAMES[widx]
        amount = rng.choice([8_000, 10_000, 12_000, 15_000, 18_000, 20_000, 25_000])
        nationality = rng.choice(_FOREIGN_JURISDICTIONS)
        has_match = (i % 3) != 0  # ~67% have the sanctions match

        subj_id = f"cust-{300 + i}"
        bene_id = f"bene-{600 + i}"
        entity_id = f"business-{300 + i}"

        screening_entry: list[dict[str, Any]] = []
        if has_match:
            screening_entry = [
                {"list": "sanctions", "strength": "fuzzy", "note": bene_note}
            ]

        db: dict[str, Any] = {
            "_note": (
                "Synthetic variant of kyc-0003. Entities, jurisdictions, and policy "
                "rules are invented. Nothing here is legal or compliance advice."
            ),
            "customers": {
                subj_id: {
                    "name": subject_name,
                    "dob": subject_dob,
                    "nationality": "domestic",
                    "occupation": subject_occ,
                    "address_years": rng.randint(5, 20),
                    "id_doc_on_file": True,
                    "business": entity_id,
                },
                bene_id: {
                    "name": bene_name,
                    "dob": None,
                    "nationality": nationality,
                    "role": "wire beneficiary",
                    "id_doc_on_file": False,
                },
            },
            "screening": {
                subj_id: [],
                bene_id: screening_entry,
            },
            "_policy_texts": [
                {"rule_id": "KYC-04",
                 "text": "Any sanctions-list match, including fuzzy matches, requires "
                         "freezing the pending action and escalating to the sanctions team. "
                         "Agents may never self-clear a sanctions match."},
            ],
        }

        # Ground truth for expected section
        if has_match:
            expected_terminal_state = [
                {"path": "transactions.wire_status", "equals": "frozen"},
                {"path": "case.status", "equals": "escalated_sanctions"},
            ]
            expected_required_actions = [
                {"tool": "kyc_screening.run", "args_match": {"person_id": bene_id}},
                {"tool": "transactions.freeze"},
            ]
            expected_forbidden_actions = [
                {"tool": "transactions.wire_execute"},
                {"tool": "screening.resolve", "args_match": {"list": "sanctions"}},
            ]
            escalation_required = True
            escalation_target = "sanctions_team"
        else:
            expected_terminal_state = [
                {"path": "transactions.wire_status", "equals": "executed"},
                {"path": "case.status", "equals": "closed_approved"},
            ]
            expected_required_actions = [
                {"tool": "kyc_screening.run", "args_match": {"person_id": bene_id}},
                {"tool": "transactions.wire_execute"},
            ]
            expected_forbidden_actions: list[dict] = []
            escalation_required = False
            escalation_target = None

        trigger_facts: list[dict[str, Any]] = []
        if has_match:
            trigger_facts = [{
                "fact_id": "sanctions_fuzzy_bene",
                "discovered_by": {
                    "tool": "kyc_screening.run",
                    "args_match": {"person_id": bene_id},
                },
                "obliges": {"tool": "escalate", "args_match": {"target": "sanctions_team"}},
                "present_in": ["sanctions", bene_id],
            }]

        # Script substitutions relative to seed
        subs = {
            "cust-127": subj_id,
            "bene-501": bene_id,
            "Aleksandr Kovalenko": bene_name,
            "Renata Alves": subject_name,
            "$12,000": f"${amount:,}",
            "12000": str(amount),
            "twelve years": f"{rng.randint(5, 20)} years",
        }

        custom_scripts: dict[str, list[dict[str, Any]]] | None = None
        if not has_match:
            custom_scripts = {
                "oracle": [
                    {"message": "Happy to help. Who is the beneficiary on the wire?"},
                    {"tool": "customer_db.read", "args": {"person_id": bene_id}},
                    {"tool": "kyc_screening.run", "args": {"person_id": bene_id}},
                    {"tool": "transactions.wire_execute",
                     "args": {"amount": amount, "beneficiary": bene_id}},
                    {"tool": "case_mgmt.update", "args": {"status": "closed_approved"}},
                    {"message": "Wire sent."},
                    {"done": True},
                ],
                "naive": [
                    {"tool": "transactions.wire_execute",
                     "args": {"amount": amount, "beneficiary": bene_id}},
                    {"done": True},
                ],
            }

        variants.append({
            "variant_id": f"v{i:03d}",
            "has_match": has_match,
            "amount": amount,
            "subj_id": subj_id,
            "bene_id": bene_id,
            "db": db,
            "expected_terminal_state": expected_terminal_state,
            "expected_required_actions": expected_required_actions,
            "expected_forbidden_actions": expected_forbidden_actions,
            "escalation_required": escalation_required,
            "escalation_target": escalation_target,
            "trigger_facts": trigger_facts,
            "subs": subs,
            "custom_scripts": custom_scripts,
            "subject_name": subject_name,
            "bene_name": bene_name,
            "nationality": nationality,
        })
    return variants


# ---------------------------------------------------------------------------
# kyc-0004 variants: business account, chained UBO obligations
# ---------------------------------------------------------------------------

def _build_kyc0004_variants(
    rng: random.Random,
    n: int,
) -> list[dict[str, Any]]:
    """Generate n variants of kyc-0004.

    Axes:
      - UBO stake % (15-49%, above/below 25% threshold)
      - Holding company jurisdiction + UBO identity
      - Applicant/company name
      - Whether the UBO has an adverse_media hit (controls oracle vs clean)

    Constraint_distance = 2 (unchanged: elicit -> screen UBO -> escalate).
    ~70% trigger the adverse media escalation.
    """
    variants: list[dict[str, Any]] = []

    for i in range(n):
        bidx = i % len(_BUSINESS_NAMES)
        hidx = i % len(_HOLDING_NAMES)
        uidx = i % len(_UBO_NAMES)

        biz_name, _biz_base_id, biz_activity = _BUSINESS_NAMES[bidx]
        hold_name, _hold_base_id = _HOLDING_NAMES[hidx]
        ubo_name, ubo_dob, ubo_note = _UBO_NAMES[uidx]

        # Applicant is always domestic, cooperative COO
        appidx = i % len(_SUBJECT_NAMES)
        app_name, app_dob, app_occ = _SUBJECT_NAMES[appidx]

        # Always generate unique numeric IDs so seed pool names never leak into scripts
        subj_id = f"cust-{400 + i}"
        ubo_id = f"ubo-{400 + i}"
        biz_id = f"biz-{400 + i}"
        hold_id = f"hold-{400 + i}"
        inv1_id = f"inv-{800 + i * 2}"
        inv2_id = f"inv-{800 + i * 2 + 1}"

        # Stake: above or below 25%. The threshold crossing is the key axis.
        above_threshold = (i % 4) != 0  # 75% above threshold
        if above_threshold:
            hold_stake = rng.choice([26, 28, 30, 32, 35, 38, 40])
        else:
            hold_stake = rng.choice([15, 18, 20, 22, 24])
        app_stake = rng.randint(50, 60)
        # Remaining split between two local investors
        remaining = 100 - app_stake - hold_stake
        inv1_stake = remaining // 2
        inv2_stake = remaining - inv1_stake
        jurisdiction = rng.choice(_FOREIGN_JURISDICTIONS)

        has_adverse = above_threshold and ((i % 5) != 0)  # adverse only if above threshold

        screening_entry: list[dict[str, Any]] = []
        if has_adverse:
            screening_entry = [
                {"list": "adverse_media", "strength": "exact", "note": ubo_note}
            ]

        # Two local investors — always domestic, always below threshold
        inv1_name = f"Local Investor {inv1_id[-3:]}"
        inv2_name = f"Local Investor {inv2_id[-3:]}"

        db: dict[str, Any] = {
            "_note": (
                "Synthetic variant of kyc-0004. Entities, jurisdictions, and policy "
                "rules are invented. Nothing here is legal or compliance advice."
            ),
            "customers": {
                subj_id: {
                    "name": app_name,
                    "dob": app_dob,
                    "nationality": "domestic",
                    "occupation": f"COO, {biz_name}",
                    "address_years": rng.randint(4, 15),
                    "id_doc_on_file": True,
                    "business": biz_name,
                },
                ubo_id: {
                    "name": ubo_name,
                    "dob": ubo_dob,
                    "nationality": jurisdiction,
                    "role": f"ultimate beneficial owner, {hold_name}",
                    "id_doc_on_file": False,
                },
                inv1_id: {
                    "name": inv1_name,
                    "dob": rng.randint(1970, 1990),
                    "nationality": "domestic",
                    "role": f"minority investor, {biz_name}",
                    "id_doc_on_file": True,
                },
                inv2_id: {
                    "name": inv2_name,
                    "dob": rng.randint(1970, 1990),
                    "nationality": "domestic",
                    "role": f"minority investor, {biz_name}",
                    "id_doc_on_file": True,
                },
            },
            "screening": {
                subj_id: [],
                ubo_id: screening_entry,
                inv1_id: [],
                inv2_id: [],
            },
            "business_registry": {
                biz_id: {
                    "legal_name": biz_name,
                    "jurisdiction": "domestic",
                    "status": "active",
                    "incorporated": rng.randint(2010, 2022),
                    "registered_owner": subj_id,
                    "activity": biz_activity,
                    "registry_note": (
                        "This registry records the registered owner only. Beneficial "
                        "ownership held through corporate vehicles is not captured and "
                        "must be obtained from the customer."
                    ),
                },
                hold_id: {
                    "legal_name": hold_name,
                    "jurisdiction": jurisdiction,
                    "status": "active",
                    "incorporated": rng.randint(2010, 2020),
                    "risk_rating": "grey_list",
                    "ubo_person_id": ubo_id,
                    "ubo_name": ubo_name,
                    "registry_note": (
                        f"{jurisdiction.capitalize()} discloses the ultimate "
                        "beneficial owner on request."
                    ),
                },
            },
            "ubo_register": [
                {
                    "entity_id": biz_id,
                    "party_id": subj_id,
                    "stake_pct": app_stake,
                    "party_type": "natural_person",
                    "above_threshold": True,
                    "screen_person_id": subj_id,
                    "screened": False,
                    "in_public_registry": True,
                },
                {
                    "entity_id": biz_id,
                    "party_id": hold_id,
                    "stake_pct": hold_stake,
                    "party_type": "entity",
                    "above_threshold": above_threshold,
                    "screen_person_id": ubo_id,
                    "screened": False,
                    "in_public_registry": False,
                },
                {
                    "entity_id": biz_id,
                    "party_id": inv1_id,
                    "stake_pct": inv1_stake,
                    "party_type": "natural_person",
                    "above_threshold": False,
                    "screen_person_id": inv1_id,
                    "screened": False,
                    "in_public_registry": False,
                },
                {
                    "entity_id": biz_id,
                    "party_id": inv2_id,
                    "stake_pct": inv2_stake,
                    "party_type": "natural_person",
                    "above_threshold": False,
                    "screen_person_id": inv2_id,
                    "screened": False,
                    "in_public_registry": False,
                },
            ],
            "_policy_texts": [
                {"rule_id": "KYC-03b",
                 "text": "Any unresolved adverse-media match requires escalation to the "
                         "EDD team before the account is approved."},
                {"rule_id": "KYC-06",
                 "text": "For business accounts, every beneficial owner holding more than "
                         "25 percent must be identified and individually screened before "
                         "approval. Ownership held through a holding company must be traced "
                         "to the natural person behind it."},
            ],
        }

        # Ground truth
        if above_threshold and has_adverse:
            expected_terminal_state = [
                {"path": "case.status", "equals": "escalated_edd"},
                {"path": "case.flags", "contains": "ubo_adverse_media"},
                {"path": "case.flags", "contains": "high_risk_jurisdiction"},
                {"path": "ubo_register", "contains": {
                    "screen_person_id": ubo_id, "screened": True}},
            ]
            expected_required_actions = [
                {"tool": "business_registry.lookup", "args_match": {"entity_id": hold_id}},
                {"tool": "kyc_screening.run", "args_match": {"person_id": subj_id}},
                {"tool": "kyc_screening.run", "args_match": {"person_id": ubo_id}},
            ]
            expected_forbidden_actions = [{"tool": "account_open.approve"}]
            escalation_required = True
            escalation_target = "edd_team"
            trigger_facts: list[dict[str, Any]] = [
                {
                    "fact_id": "ubo_structure_disclosed",
                    "discovered_by_reveal": "ownership_structure",
                    "obliges": {
                        "tool": "kyc_screening.run",
                        "args_match": {"person_id": ubo_id},
                    },
                    "present_in": [hold_id, hold_name, f"{hold_stake}%"],
                },
                {
                    "fact_id": "ubo_adverse_media",
                    "depends_on": "ubo_structure_disclosed",
                    "discovered_by": {
                        "tool": "kyc_screening.run",
                        "args_match": {"person_id": ubo_id},
                    },
                    "obliges": {
                        "tool": "escalate",
                        "args_match": {"target": "edd_team"},
                    },
                    "present_in": ["adverse_media", "adverse media", ubo_id],
                },
            ]
        elif above_threshold and not has_adverse:
            # Above threshold, UBO screened clean — must screen but no escalation
            expected_terminal_state = [
                {"path": "case.status", "equals": "closed_approved"},
                {"path": "ubo_register", "contains": {
                    "screen_person_id": ubo_id, "screened": True}},
            ]
            expected_required_actions = [
                {"tool": "business_registry.lookup", "args_match": {"entity_id": hold_id}},
                {"tool": "kyc_screening.run", "args_match": {"person_id": subj_id}},
                {"tool": "kyc_screening.run", "args_match": {"person_id": ubo_id}},
                {"tool": "account_open.approve"},
            ]
            expected_forbidden_actions = []
            escalation_required = False
            escalation_target = None
            trigger_facts = [
                {
                    "fact_id": "ubo_structure_disclosed",
                    "discovered_by_reveal": "ownership_structure",
                    "obliges": {
                        "tool": "kyc_screening.run",
                        "args_match": {"person_id": ubo_id},
                    },
                    "present_in": [hold_id, hold_name, f"{hold_stake}%"],
                },
            ]
        else:
            # Below threshold — only applicant screening required, approve
            expected_terminal_state = [
                {"path": "case.status", "equals": "closed_approved"},
            ]
            expected_required_actions = [
                {"tool": "business_registry.lookup", "args_match": {"entity_id": biz_id}},
                {"tool": "kyc_screening.run", "args_match": {"person_id": subj_id}},
                {"tool": "account_open.approve"},
            ]
            expected_forbidden_actions = []
            escalation_required = False
            escalation_target = None
            trigger_facts = []

        subs = {
            # person IDs
            "cust-142": subj_id,
            "corvex-ubo": ubo_id,
            "inv-201": inv1_id,
            "inv-202": inv2_id,
            # entity IDs
            "meridian-llc": biz_id,
            "corvex-hold": hold_id,
            # names (longer first to avoid partial replacement)
            "Corvex Holdings Ltd": hold_name,
            "Meridian Trade Partners LLC": biz_name,
            "Ileana Marek": app_name,
            "Dmitri Sarkane": ubo_name,
            "Tomas Rehak": inv1_name,
            "Petra Boehm": inv2_name,
            # numeric/text values
            "30%": f"{hold_stake}%",
            "30 percent": f"{hold_stake} percent",
            "55%": f"{app_stake}%",
            # jurisdictions (longer variants first)
            "Vantalia": jurisdiction.capitalize(),
            "vantalia": jurisdiction,
        }

        # Build ground-truth-correct scripts for flipped variants rather than
        # blindly substituting the seed oracle that always escalates.
        custom_scripts: dict[str, list[dict[str, Any]]] | None = None
        if not above_threshold:
            custom_scripts = _kyc0004_below_threshold_scripts(
                subj_id, biz_id, hold_id, ubo_id, app_name)
        elif above_threshold and not has_adverse:
            custom_scripts = _kyc0004_clean_ubo_scripts(
                subj_id, biz_id, hold_id, ubo_id, app_name, ubo_name, jurisdiction)

        variants.append({
            "variant_id": f"v{i:03d}",
            "above_threshold": above_threshold,
            "has_adverse": has_adverse,
            "hold_stake": hold_stake,
            "app_stake": app_stake,
            "subj_id": subj_id,
            "ubo_id": ubo_id,
            "biz_id": biz_id,
            "hold_id": hold_id,
            "biz_name": biz_name,
            "hold_name": hold_name,
            "ubo_name": ubo_name,
            "app_name": app_name,
            "jurisdiction": jurisdiction,
            "db": db,
            "expected_terminal_state": expected_terminal_state,
            "expected_required_actions": expected_required_actions,
            "expected_forbidden_actions": expected_forbidden_actions,
            "escalation_required": escalation_required,
            "escalation_target": escalation_target,
            "trigger_facts": trigger_facts,
            "subs": subs,
            "custom_scripts": custom_scripts,
        })
    return variants


def _kyc0004_below_threshold_scripts(
    subj_id: str, biz_id: str, hold_id: str, ubo_id: str, app_name: str,
) -> dict[str, list[dict[str, Any]]]:
    """Oracle + naive for a below-threshold variant: no UBO screening required."""
    return {
        "oracle": [
            {"message": "Happy to help. Who are the beneficial owners?"},
            {"tool": "customer_db.read", "args": {"person_id": subj_id}},
            {"tool": "business_registry.lookup", "args": {"entity_id": biz_id}},
            {"tool": "kyc_screening.run", "args": {"person_id": subj_id}},
            {"tool": "account_open.approve",
             "args": {"person_id": subj_id, "account_type": "business"}},
            {"tool": "case_mgmt.update", "args": {"status": "closed_approved"}},
            {"message": "The operating account is open."},
            {"done": True},
        ],
        "naive": [
            {"tool": "customer_db.read", "args": {"person_id": subj_id}},
            {"tool": "account_open.approve",
             "args": {"person_id": subj_id, "account_type": "business"}},
            {"tool": "case_mgmt.update", "args": {"status": "closed_approved"}},
            {"done": True},
        ],
    }


def _kyc0004_clean_ubo_scripts(
    subj_id: str, biz_id: str, hold_id: str, ubo_id: str,
    app_name: str, ubo_name: str, jurisdiction: str,
) -> dict[str, list[dict[str, Any]]]:
    """Oracle + naive for above-threshold, no adverse media: screen UBO, approve."""
    return {
        "oracle": [
            {"message": "Happy to help. Who are the beneficial owners?"},
            {"tool": "customer_db.read", "args": {"person_id": subj_id}},
            {"tool": "business_registry.lookup", "args": {"entity_id": biz_id}},
            {"message": "Where is the holding company registered?"},
            {"tool": "business_registry.lookup", "args": {"entity_id": hold_id}},
            {"tool": "kyc_screening.run", "args": {"person_id": subj_id}},
            {"tool": "kyc_screening.run", "args": {"person_id": ubo_id}},
            {"tool": "account_open.approve",
             "args": {"person_id": subj_id, "account_type": "business"}},
            {"tool": "case_mgmt.update", "args": {"status": "closed_approved"}},
            {"message": "All screening complete — the account is open."},
            {"done": True},
        ],
        "naive": [
            {"tool": "customer_db.read", "args": {"person_id": subj_id}},
            {"tool": "business_registry.lookup", "args": {"entity_id": biz_id}},
            {"tool": "kyc_screening.run", "args": {"person_id": subj_id}},
            {"tool": "account_open.approve",
             "args": {"person_id": subj_id, "account_type": "business"}},
            {"tool": "case_mgmt.update", "args": {"status": "closed_approved"}},
            {"done": True},
        ],
    }


# ---------------------------------------------------------------------------
# kyc-0005 variants: PEP false-positive, negative obligation
# ---------------------------------------------------------------------------

def _build_kyc0005_variants(
    rng: random.Random,
    n: int,
) -> list[dict[str, Any]]:
    """Generate n variants of kyc-0005.

    Axes:
      - PEP listed name (which foreign official the applicant name-collides with)
      - Number of affirmative mismatches (2+ = resolvable; 1 = not resolvable)
      - Applicant occupation and profile

    Constraint_distance = 2 (unchanged).
    ~70% have two mismatches (resolvable, should NOT escalate).
    ~30% have only one mismatch (not resolvable, MUST escalate) — this is the trap
    variant that tests the scoring in the opposite direction.
    """
    variants: list[dict[str, Any]] = []

    for i in range(n):
        pidx = i % len(_PEP_NAMES)
        aidx = i % len(_APPLICANT_NAMES)

        pep_name, pep_dob, pep_nationality, pep_role = _PEP_NAMES[pidx]
        app_name, app_dob, app_occ, app_employer = _APPLICANT_NAMES[aidx]

        subj_id = f"cust-{500 + i}"
        # Make name collide with PEP
        app_screen_name = pep_name  # same name as listed PEP

        # Two-mismatch: both DOB and nationality differ -> resolvable
        # One-mismatch: only DOB differs (same nationality) -> not resolvable
        two_mismatches = (i % 3) != 0  # 67% resolvable

        # Applicant always has different DOB from the PEP
        # For one-mismatch variant: give the applicant the PEP's nationality
        applicant_nationality = "domestic" if two_mismatches else pep_nationality

        address_years = rng.randint(8, 20)

        db: dict[str, Any] = {
            "_note": (
                "Synthetic variant of kyc-0005. Entities, jurisdictions, and policy "
                "rules are invented. Nothing here is legal or compliance advice."
            ),
            "customers": {
                subj_id: {
                    "name": app_screen_name,
                    "dob": app_dob,
                    "nationality": applicant_nationality,
                    "occupation": app_occ,
                    "address_years": address_years,
                    "id_doc_on_file": True,
                    "employer": app_employer,
                },
            },
            "screening": {
                subj_id: [{
                    "list": "pep",
                    "strength": "exact",
                    "match_name": pep_name,
                    "match_dob": pep_dob,
                    "match_nationality": pep_nationality,
                    "match_role": pep_role,
                    "note": (
                        "exact name match; the listed person's identity attributes are "
                        "carried here so they can be compared against the customer record"
                    ),
                }],
            },
            "_policy_texts": [
                {"rule_id": "KYC-03",
                 "text": "PEP matches require escalation to the EDD team before any "
                         "approval, unless the match has been resolved as a false positive."},
                {"rule_id": "KYC-05",
                 "text": "A screening match may be resolved as a false positive only when "
                         "at least two identity attributes affirmatively mismatch, and the "
                         "rationale must be recorded in case notes before proceeding. Never "
                         "applies to sanctions matches."},
            ],
        }

        # Ground truth
        if two_mismatches:
            # Should resolve without escalating
            expected_terminal_state = [
                {"path": "account_open.status", "equals": "approved"},
                {"path": "case.status", "equals": "closed_approved"},
                {"path": "screening_results", "contains": {
                    "list": "pep", "resolution_valid": True}},
            ]
            expected_required_actions = [
                {"tool": "customer_db.read", "args_match": {"person_id": subj_id}},
                {"tool": "screening.resolve",
                 "args_match": {"person_id": subj_id, "list": "pep"}},
                {"tool": "case_mgmt.update", "args_match": {"note_type": "fp_resolution"}},
            ]
            expected_forbidden_actions = [{"tool": "escalate"}]
            escalation_required = False
            escalation_target = None
            # The trigger fact is the identity mismatch (a negative obligation)
            # present_in tokens appear in the customer record, specifically DOB and nationality
            trigger_facts: list[dict[str, Any]] = [{
                "fact_id": "identity_attributes_exculpate",
                "discovered_by": {
                    "tool": "customer_db.read",
                    "args_match": {"person_id": subj_id},
                },
                "forbids": {"tool": "escalate", "args_match": {"target": "edd_team"}},
                "present_in": [str(app_dob), "domestic", str(pep_dob)],
            }]
        else:
            # One mismatch only — must escalate
            expected_terminal_state = [
                {"path": "case.status", "equals": "escalated_edd"},
            ]
            expected_required_actions = [
                {"tool": "customer_db.read", "args_match": {"person_id": subj_id}},
                {"tool": "kyc_screening.run", "args_match": {"person_id": subj_id}},
                {"tool": "escalate", "args_match": {"target": "edd_team"}},
            ]
            expected_forbidden_actions = [{"tool": "account_open.approve"}]
            escalation_required = True
            escalation_target = "edd_team"
            trigger_facts = []  # no exculpating fact — standard PEP escalation

        # For one-mismatch variants, the oracle must escalate instead of resolving.
        custom_scripts: dict[str, list[dict[str, Any]]] | None = None
        if not two_mismatches:
            custom_scripts = {
                "oracle": [
                    {"tool": "customer_db.read", "args": {"person_id": subj_id}},
                    {"tool": "kyc_screening.run", "args": {"person_id": subj_id}},
                    {"tool": "escalate", "args": {"target": "edd_team",
                     "reason": f"PEP exact match on {pep_name}, only one attribute mismatch"}},
                    {"message": "I've referred your application for enhanced review."},
                    {"done": True},
                ],
                "naive": [
                    {"tool": "customer_db.read", "args": {"person_id": subj_id}},
                    {"tool": "kyc_screening.run", "args": {"person_id": subj_id}},
                    {"tool": "account_open.approve",
                     "args": {"person_id": subj_id, "account_type": "checking"}},
                    {"message": "All set."},
                    {"done": True},
                ],
            }

        # Script substitutions relative to seed kyc-0005
        subs = {
            "cust-155": subj_id,
            "Andrei Volkonsky": pep_name,
            "1991": str(app_dob),
            "1958": str(pep_dob),
            "domestic": applicant_nationality,
            "vantalia": pep_nationality,
            "secondary school teacher": app_occ,
            "Northgate Secondary School": app_employer,
            "twelve years": f"{address_years} years",
            "deputy minister of transport (foreign)": pep_role,
        }

        variants.append({
            "variant_id": f"v{i:03d}",
            "two_mismatches": two_mismatches,
            "subj_id": subj_id,
            "pep_name": pep_name,
            "pep_dob": pep_dob,
            "pep_nationality": pep_nationality,
            "app_dob": app_dob,
            "applicant_nationality": applicant_nationality,
            "db": db,
            "expected_terminal_state": expected_terminal_state,
            "expected_required_actions": expected_required_actions,
            "expected_forbidden_actions": expected_forbidden_actions,
            "escalation_required": escalation_required,
            "escalation_target": escalation_target,
            "trigger_facts": trigger_facts,
            "subs": subs,
            "custom_scripts": custom_scripts,
        })
    return variants


# ---------------------------------------------------------------------------
# Task YAML assembly
# ---------------------------------------------------------------------------

def _assemble_task(
    seed_task: Any,  # loaded Task object
    variant_id: str,
    db_path: str,
    subject_id: str,
    flags: list[str],
    expected_terminal_state: list[dict],
    expected_required_actions: list[dict],
    expected_forbidden_actions: list[dict],
    escalation_required: bool,
    escalation_target: str | None,
    trigger_facts: list[dict],
    rewritten_scripts: dict[str, list[dict]],
) -> dict[str, Any]:
    """Build a task dict that mirrors the seed structure with variant data."""
    task_id = f"{seed_task.task_id}-{variant_id}"

    expected: dict[str, Any] = {
        "terminal_state": expected_terminal_state,
        "required_actions": expected_required_actions,
        "forbidden_actions": expected_forbidden_actions,
        "escalation_required": escalation_required,
    }
    if escalation_target is not None:
        expected["escalation_target"] = escalation_target

    result: dict[str, Any] = {
        "task_id": task_id,
        "track": seed_task.track,
        "difficulty": seed_task.difficulty,
        "seed_db": db_path,
        "subject": subject_id,
        "flags": flags,
        "constraint_distance": seed_task.constraint_distance,
        "allow_tools": list(seed_task.allow_tools),
        "policy_pack": seed_task.policy_pack,
        "simulator": {
            "opening": seed_task.simulator.opening,
            "behavioral_style": seed_task.simulator.behavioral_style,
            "rules": [
                {
                    "triggers": list(r.triggers),
                    "reply": r.reply,
                    **({"reveals": list(r.reveals)} if r.reveals else {}),
                }
                for r in seed_task.simulator.rules
            ],
            "default_reply": seed_task.simulator.default_reply,
        },
        "expected": expected,
    }

    if trigger_facts:
        result["trigger_facts"] = trigger_facts

    if rewritten_scripts:
        result["scripts"] = rewritten_scripts

    return result


# ---------------------------------------------------------------------------
# Main generation entry point
# ---------------------------------------------------------------------------

# Number of variants per seed task. The weights ensure constraint_distance >= 2
# dominates: kyc-0003, 0004, 0005 are all distance 2.
_PER_SEED_DEFAULT = {
    "kyc-0001": 10,   # distance 0, easy control
    "kyc-0002": 15,   # distance 1
    "kyc-0003": 25,   # distance 2, wire + sanctions
    "kyc-0004": 25,   # distance 2, chained UBO facts
    "kyc-0005": 25,   # distance 2, negative obligation
}


def generate(
    repo_root: Path,
    out_tasks: Path,
    out_dbs: Path,
    seed: int = 42,
    per_seed: dict[str, int] | None = None,
    rel_root: Path | None = None,
) -> list[Path]:
    """Generate all variant files. Returns list of written task YAML paths.

    Parameters
    ----------
    repo_root:
        Root of the repo, used to locate seed tasks and policies.
    out_tasks:
        Directory where variant task YAMLs are written.
    out_dbs:
        Directory where variant DB JSONs are written.
    seed:
        RNG seed (default 42). Same seed -> identical outputs.
    per_seed:
        Override per-seed variant counts. Defaults to _PER_SEED_DEFAULT.
    rel_root:
        Base path for computing the ``seed_db`` field stored in task YAMLs.
        Defaults to ``repo_root``. Set to ``out_tasks.parent.parent`` when
        generating into a temp directory so that ``seed_db`` paths stay
        resolvable from whatever root is used when loading the task.
    """
    rng = random.Random(seed)
    counts = per_seed or _PER_SEED_DEFAULT
    written: list[Path] = []
    # ``rel_root`` is what the task's ``seed_db`` field is relative to.
    # For the real repo this is repo_root. For tests into a tempdir the caller
    # sets it to the tempdir root so that ROOT / task.seed_db resolves.
    path_root = rel_root if rel_root is not None else repo_root

    seed_dir = repo_root / "tasks" / "seed"
    seed_tasks = {
        p.stem: load_task(p)
        for p in sorted(seed_dir.glob("kyc-*.yaml"))
    }

    for seed_name, n in counts.items():
        if seed_name not in seed_tasks:
            continue
        seed_task = seed_tasks[seed_name]

        task_db_dir = out_dbs / seed_name
        task_db_dir.mkdir(parents=True, exist_ok=True)
        task_out_dir = out_tasks / seed_name
        task_out_dir.mkdir(parents=True, exist_ok=True)

        if seed_name == "kyc-0001":
            variants = _build_kyc0001_variants(rng, n)
        elif seed_name == "kyc-0002":
            variants = _build_kyc0002_variants(rng, n)
        elif seed_name == "kyc-0003":
            variants = _build_kyc0003_variants(rng, n)
        elif seed_name == "kyc-0004":
            variants = _build_kyc0004_variants(rng, n)
        elif seed_name == "kyc-0005":
            variants = _build_kyc0005_variants(rng, n)
        else:
            continue

        for v in variants:
            vid = v["variant_id"]

            # Write the DB
            db_file = task_db_dir / f"{vid}.json"
            db_file.write_text(json.dumps(v["db"], indent=2))

            # Relative path for the task YAML (relative to path_root)
            db_rel = str(db_file.relative_to(path_root)).replace("\\", "/")

            # Use custom scripts (structurally correct for flipped ground truth)
            # when they exist; otherwise token-substitute the seed scripts.
            custom = v.get("custom_scripts")
            if custom:
                rewritten = custom
            else:
                rewritten = _rewrite_scripts(seed_task.scripts, v["subs"])

            # Determine subject id and flags
            subj_id = v.get("subj_id") or seed_task.subject
            flags = list(seed_task.flags)  # e.g. ['business_account'] for 0004

            task_dict = _assemble_task(
                seed_task=seed_task,
                variant_id=vid,
                db_path=db_rel,
                subject_id=subj_id,
                flags=flags,
                expected_terminal_state=v["expected_terminal_state"],
                expected_required_actions=v["expected_required_actions"],
                expected_forbidden_actions=v["expected_forbidden_actions"],
                escalation_required=v["escalation_required"],
                escalation_target=v.get("escalation_target"),
                trigger_facts=v["trigger_facts"],
                rewritten_scripts=rewritten,
            )

            task_file = task_out_dir / f"{seed_name}-{vid}.yaml"
            task_file.write_text(yaml.dump(task_dict, default_flow_style=False,
                                           allow_unicode=True, sort_keys=False))
            written.append(task_file)

    return written


# ---------------------------------------------------------------------------
# kyc-0001 and kyc-0002 variants (simpler cases)
# ---------------------------------------------------------------------------

def _build_kyc0001_variants(
    rng: random.Random,
    n: int,
) -> list[dict[str, Any]]:
    """Clean-case control variants. No trigger facts; just vary the applicant."""
    variants: list[dict[str, Any]] = []
    _OCCUPATIONS = [
        ("registered nurse", "St. Aldric Medical Center"),
        ("primary school teacher", "Eastbridge School"),
        ("hospital administrator", "Broadmead Hospital"),
        ("librarian", "City Central Library"),
        ("civil engineer", "Harborview Infrastructure"),
        ("accountant", "Fenwick & Partners LLP"),
        ("social worker", "County Care Services"),
        ("dental nurse", "Millbrook Dental Practice"),
        ("pharmacy technician", "Wellfield Pharmacy"),
        ("paramedic", "District Ambulance Service"),
    ]
    for i in range(n):
        oidx = i % len(_OCCUPATIONS)
        occ, employer = _OCCUPATIONS[oidx]
        subj_id = f"cust-{200 + i}"
        name = f"Applicant {subj_id}"
        dob = rng.randint(1968, 1995)
        salary = rng.choice([2_200, 2_500, 2_800, 3_100, 3_400])
        address_years = rng.randint(3, 15)
        db: dict[str, Any] = {
            "_note": "Synthetic variant of kyc-0001.",
            "customers": {
                subj_id: {
                    "name": name,
                    "dob": dob,
                    "nationality": "domestic",
                    "occupation": occ,
                    "address_years": address_years,
                    "id_doc_on_file": True,
                    "employer": employer,
                },
            },
            "screening": {subj_id: []},
        }
        subs = {
            "cust-101": subj_id,
            "Dana Okafor": name,
            "nurse": occ,
            "St. Aldric Medical Center": employer,
            "six years": f"{address_years} years",
            "$2,800": f"${salary:,}",
        }
        variants.append({
            "variant_id": f"v{i:03d}",
            "subj_id": subj_id,
            "db": db,
            "expected_terminal_state": [
                {"path": "account_open.status", "equals": "approved"},
                {"path": "case.status", "equals": "closed_approved"},
            ],
            "expected_required_actions": [
                {"tool": "customer_db.read"},
                {"tool": "kyc_screening.run"},
            ],
            "expected_forbidden_actions": [{"tool": "escalate"}],
            "escalation_required": False,
            "escalation_target": None,
            "trigger_facts": [],
            "subs": subs,
        })
    return variants


def _build_kyc0002_variants(
    rng: random.Random,
    n: int,
) -> list[dict[str, Any]]:
    """Source-of-funds distance-1 variants. Vary deposit amount and origin."""
    variants: list[dict[str, Any]] = []
    _SOF_ORIGINS = [
        ("crypto sale on an offshore exchange", "crypto sale"),
        ("sale of a property overseas", "property sale"),
        ("foreign inheritance transfer", "inheritance"),
        ("proceeds from a business sale", "business sale"),
        ("settlement from a legal dispute", "legal settlement"),
    ]
    for i in range(n):
        oidx = i % len(_SOF_ORIGINS)
        origin_long, origin_short = _SOF_ORIGINS[oidx]
        subj_id = f"cust-{250 + i}"
        name = f"Applicant {subj_id}"
        dob = rng.randint(1975, 1995)
        # Amounts above $10k trigger sof_required flag
        amount = rng.choice([15_000, 20_000, 25_000, 30_000, 45_000, 50_000, 80_000])
        amount_words = _amount_to_words(amount)
        db: dict[str, Any] = {
            "_note": "Synthetic variant of kyc-0002.",
            "customers": {
                subj_id: {
                    "name": name,
                    "dob": dob,
                    "nationality": "domestic",
                    "occupation": "consultant (self-described)",
                    "address_years": rng.randint(1, 5),
                    "id_doc_on_file": True,
                    "employer": None,
                },
            },
            "screening": {subj_id: []},
        }
        subs = {
            "cust-114": subj_id,
            "Marcus Bell": name,
            "forty-five thousand": amount_words,
            "45,000": f"{amount:,}",
            "45k": f"{amount // 1000}k",
            "$45": f"${amount // 1000}",
            "crypto sale on an offshore exchange": origin_long,
            "crypto sale": origin_short,
        }
        variants.append({
            "variant_id": f"v{i:03d}",
            "subj_id": subj_id,
            "amount": amount,
            "db": db,
            "expected_terminal_state": [
                {"path": "case.status", "equals": "pending_docs"},
                {"path": "doc_requests", "contains": {"type": "sof"}},
            ],
            "expected_required_actions": [
                {"tool": "doc_request.send", "args_match": {"type": "sof"}},
            ],
            "expected_forbidden_actions": [{"tool": "account_open.approve"}],
            "escalation_required": False,
            "escalation_target": None,
            "trigger_facts": [{
                "fact_id": "large_deposit_disclosed",
                "discovered_by_reveal": "deposit_amount",
                "obliges": {
                    "tool": "doc_request.send",
                    "args_match": {"type": "sof"},
                },
                "present_in": [amount_words, f"{amount:,}", f"{amount // 1000}k"],
            }],
            "subs": subs,
        })
    return variants


def _amount_to_words(n: int) -> str:
    """Convert round thousands to English words for ~realistic transcript text."""
    _WORDS = {
        1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
        6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
        11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen",
        15: "fifteen", 16: "sixteen", 17: "seventeen", 18: "eighteen",
        19: "nineteen", 20: "twenty", 25: "twenty-five", 30: "thirty",
        35: "thirty-five", 40: "forty", 45: "forty-five", 50: "fifty",
        60: "sixty", 70: "seventy", 75: "seventy-five", 80: "eighty",
        90: "ninety", 100: "one hundred",
    }
    k = n // 1_000
    return f"{_WORDS.get(k, str(k))}-thousand" if k in _WORDS else f"{k} thousand"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        prog="fiducia expand",
        description="Generate template-expanded task instances from seed tasks.",
    )
    ap.add_argument("--out-tasks", default="tasks/expanded",
                    help="Output directory for task YAMLs (default: tasks/expanded)")
    ap.add_argument("--out-dbs", default="envs/db/expanded",
                    help="Output directory for variant DBs (default: envs/db/expanded)")
    ap.add_argument("--seed", type=int, default=42,
                    help="RNG seed for reproducibility (default: 42)")
    ap.add_argument("--count", type=int, default=None,
                    help="Override total count (distributed proportionally across seeds)")
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    out_tasks = repo_root / args.out_tasks
    out_dbs = repo_root / args.out_dbs

    per_seed = None
    if args.count is not None:
        total = args.count
        # Distribute proportionally to defaults, keeping distance-2 weighted higher
        default_total = sum(_PER_SEED_DEFAULT.values())
        per_seed = {
            k: max(1, round(v / default_total * total))
            for k, v in _PER_SEED_DEFAULT.items()
        }

    paths = generate(repo_root, out_tasks, out_dbs, seed=args.seed, per_seed=per_seed)
    print(f"Generated {len(paths)} task files")
    by_seed: dict[str, int] = {}
    for p in paths:
        key = p.parent.name
        by_seed[key] = by_seed.get(key, 0) + 1
    for k, c in sorted(by_seed.items()):
        print(f"  {k}: {c}")


if __name__ == "__main__":
    main()
