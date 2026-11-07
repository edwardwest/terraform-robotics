"""Intervention catalog and recommender: rank landscape interventions against a goals brief and site facts.

Pure (YAML in, dicts out; no database, no network) so it is testable on its own. Every score and reason comes from
the catalog fields in rules/interventions.yaml and the facts passed in; no model is involved.

Site facts (all optional): area_m2, mean_slope_pct, main_valleys, keypoint_count, has_terrain, terrain_grade.
Brief fields: see `BRIEF_FIELDS`; goals are an ordered list, most important first.
"""

from __future__ import annotations

from functools import lru_cache
from importlib import resources
from typing import Any

import yaml

LICENSE = "Terraform Robotics intervention catalog (proprietary)"

# Weight of each goal by its position in the person's ranked list. Goals past the fifth are ignored.
PRIORITY = (1.0, 0.8, 0.65, 0.5, 0.4)
BUDGET_TIER = {"under_5k": 1, "5k_25k": 2, "25k_100k": 3, "over_100k": 4}
MAINTENANCE_LEVEL = {"low": 1, "medium": 2, "high": 3}
# Long-lived work that a tenant should agree with the owner first.
PERMANENT_PHASES = {"water", "access", "trees", "structures"}
MACHINE_WORK = {"keyline", "swale", "pond", "access-on-contour", "compost-application"}

M2_PER_ACRE = 4046.8564224
M2_PER_FT2 = 0.09290304


@lru_cache(maxsize=1)
def catalog() -> dict:
    data = yaml.safe_load(resources.files("tr_kb").joinpath("rules/interventions.yaml").read_text())
    phase_order = {p["id"]: i for i, p in enumerate(data["phases"])}
    for i in data["interventions"]:
        i.setdefault("conditions", {})
        i.setdefault("requires", [])
        i.setdefault("nrcs", [])
        i.setdefault("rules", [])
        i.setdefault("references", [])
        i.setdefault("cautions", [])
        i.setdefault("tool", None)
        i.setdefault("quantity", None)
        i.setdefault("cost_item", None)
        i["phase_order"] = phase_order[i["phase"]]
    return data


def by_id() -> dict[str, dict]:
    return {i["id"]: i for i in catalog()["interventions"]}


def option_ids(question: str) -> set[str]:
    return {o["id"] for o in catalog()["questions"][question]}


def goal_ids() -> list[str]:
    return [g["id"] for g in catalog()["goals"]]


def label(kind: str, key: str) -> str:
    for g in catalog()[kind]:
        if g["id"] == key:
            return g["label"]
    return key


# ---- Display helpers (US units for reasons; the API itself stays metric) ----------------------------


def _area(m2: float) -> str:
    acres = m2 / M2_PER_ACRE
    if acres >= 0.5:
        return f"{acres:,.1f} acres"
    return f"{m2 / M2_PER_FT2:,.0f} sq ft"


def _pct(v: float) -> str:
    return f"{v:.0f}%"


def _rain(mm: float) -> str:
    return f"{mm / 25.4:.0f} in"


def _range_text(lo, hi, fmt) -> str:
    if lo is not None and hi is not None:
        return f"{fmt(lo)} to {fmt(hi)}"
    if lo is not None:
        return f"at least {fmt(lo)}"
    return f"up to {fmt(hi)}"


# ---- Recommender --------------------------------------------------------------------------------------


def _check_range(name: str, value, bounds, fmt, site_word: str) -> str | None:
    """A concern when a known value falls outside a catalog range, else None."""
    if value is None or not bounds:
        return None
    lo, hi = (list(bounds) + [None, None])[:2]
    if (lo is not None and value < lo) or (hi is not None and value > hi):
        return f"Works best with {name} of {_range_text(lo, hi, fmt)}; {site_word} {fmt(value)}."
    return None


def _requirement(req: str, site: dict, brief: dict) -> tuple[str, str]:
    """('ok' | 'missing' | 'unknown', explanation)."""
    if req == "terrain":
        return ("ok", "") if site.get("has_terrain") else (
            "unknown", "Build the terrain model on the Survey step to check this against the land itself.")
    if req == "valley":
        if not site.get("has_terrain"):
            return "unknown", "Needs the terrain model to find valleys and keypoints."
        if (site.get("main_valleys") or 0) > 0 or (site.get("keypoint_count") or 0) > 0:
            return "ok", ""
        return "missing", "Needs a clear valley with a keypoint; the terrain model found none on this site."
    if req == "creek":
        sources = brief.get("water_sources") or []
        if "creek_spring" in sources:
            return "ok", ""
        return ("missing", "Needs a creek or spring on the land.") if sources else (
            "unknown", "Only applies if there is a creek or spring on the land.")
    if req == "buildings":
        has = brief.get("has_buildings")
        if has is True:
            return "ok", ""
        return ("missing", "Needs a house or other building on site.") if has is False else (
            "unknown", "Assumes a house or other building on site.")
    return "unknown", ""


def recommend(brief: dict | None, site: dict | None, selected: set[str] | None = None) -> list[dict]:
    """Rank every catalog intervention. Returns dicts sorted best first, with a fit of good | possible | not_suited."""
    brief, site, selected = brief or {}, site or {}, selected or set()
    goals = [g for g in (brief.get("goals") or []) if g in goal_ids()][: len(PRIORITY)]
    weight_of = {g: PRIORITY[i] for i, g in enumerate(goals)}
    budget = BUDGET_TIER.get(brief.get("budget") or "")
    appetite = MAINTENANCE_LEVEL.get(brief.get("maintenance") or "")
    constraints = set(brief.get("constraints") or [])
    out = []
    for item in catalog()["interventions"]:
        reasons, concerns, blockers, unknowns = [], [], [], []

        matched = sorted((g for g in item["goals"] if g in weight_of), key=lambda g: goals.index(g))
        goal_score = sum(item["goals"][g] * weight_of[g] for g in matched)
        for g in matched[:2]:
            rank = goals.index(g) + 1
            which = "your top goal" if rank == 1 else f"your goal #{rank}"
            verb = "A main way to meet" if item["goals"][g] >= 3 else "Helps with"
            reasons.append(f"{verb} {which}: {label('goals', g).lower()}.")

        needs_site_check = False  # a terrain-dependent requirement the app can't check yet
        for req in item["requires"]:
            if req == "valley" and not site.get("has_terrain"):
                continue  # covered by the terrain note
            state, why = _requirement(req, site, brief)
            if state == "missing":
                blockers.append(why)
            elif state == "unknown":
                unknowns.append(why)
                needs_site_check = needs_site_check or req == "terrain"

        cond = item["conditions"]
        area = site.get("area_m2")
        lo_area, hi_area = ((cond.get("area_m2") or []) + [None, None])[:2]
        if area is not None and lo_area is not None and area < lo_area:
            blockers.append(f"Needs at least {_area(lo_area)}; this site is {_area(area)}.")
        elif area is not None and hi_area is not None and area > hi_area:
            concerns.append(f"Most practical on up to {_area(hi_area)}; this site is {_area(area)}, so it may fit "
                            "one part of it.")
        slope = site.get("mean_slope_pct")
        c = _check_range("slopes", slope, cond.get("slope_pct"), _pct, "this site averages")
        if c:
            concerns.append(c + " It may still suit parts of the site.")
        elif slope is not None and cond.get("slope_pct"):
            reasons.append(f"Suits this site's average slope of {_pct(slope)}.")
        c = _check_range("annual rainfall", brief.get("annual_rainfall_mm"), cond.get("rainfall_mm"), _rain, "this site gets")
        if c:
            concerns.append(c)

        penalty = 0.0
        if budget is not None and item["cost_tier"] > budget:
            gap = item["cost_tier"] - budget
            penalty += 0.6 * gap
            concerns.append("Likely above the budget you set, at least done all at once." if gap == 1 else
                            "Well above the budget you set.")
        if appetite is not None:
            need = MAINTENANCE_LEVEL[item["maintenance"]]
            if need > appetite:
                penalty += 0.5 * (need - appetite)
                concerns.append(f"Needs {item['maintenance']} upkeep; you asked for {brief['maintenance']}.")
            elif need == 1:
                reasons.append("Low upkeep once established.")
        if "renting" in constraints and item["phase"] in PERMANENT_PHASES:
            penalty += 0.5
            concerns.append("Long-lived work: agree it with the landowner before you start.")
        if "limited_machinery" in constraints and item["id"] in MACHINE_WORK:
            penalty += 0.8
            concerns.append("Needs machinery on site, which you said is hard to get in.")
        if "sensitive_habitat" in constraints and item["category"] == "earthworks":
            concerns.append("Keep earthworks clear of the creek, wetland or protected habitat; permits may apply.")
        if "hoa" in constraints and item["id"] in ("poultry", "high-tunnel", "food-forest"):
            concerns.append("Check HOA rules before you start.")

        score = round(goal_score - penalty, 3)
        # An unanswered question never demotes a suggestion. Work that depends on the land's shape (earthworks,
        # roads) stays "worth a look" until the terrain model can check it.
        if blockers:
            fit = "not_suited"
        elif goals and goal_score >= 1.2 and score >= 1.2 and not concerns and not needs_site_check:
            fit = "good"
        else:
            fit = "possible"
        if goals and goal_score == 0 and not blockers:
            concerns.insert(0, "Doesn't serve the goals you chose, though it may still be worth knowing about.")
        out.append({
            "id": item["id"], "title": item["title"], "category": item["category"], "phase": item["phase"],
            "summary": " ".join(item["summary"].split()), "fit": fit, "score": score,
            "matched_goals": matched, "reasons": reasons, "concerns": blockers + concerns, "unknowns": unknowns,
            "cautions": item["cautions"],
            "maintenance": item["maintenance"], "cost_tier": item["cost_tier"], "nrcs": item["nrcs"],
            "rules": item["rules"], "references": item["references"], "tool": item["tool"],
            "quantity": item["quantity"], "has_allowance": bool(item["cost_item"]), "selected": item["id"] in selected,
        })
    rank = {"good": 0, "possible": 1, "not_suited": 2}
    out.sort(key=lambda r: (rank[r["fit"]], -r["score"], by_id()[r["id"]]["phase_order"], r["title"]))
    return out


def sequence(ids: list[str]) -> list[dict]:
    """Chosen interventions in the order to build them: by Yeomans' scale of permanence, then catalog order."""
    cat = by_id()
    order = {i["id"]: n for n, i in enumerate(catalog()["interventions"])}
    known = [i for i in ids if i in cat]
    return [cat[i] for i in sorted(known, key=lambda i: (cat[i]["phase_order"], order[i]))]


def quantity_in_cost_unit(basis: str, quantity: float, unit: str) -> float:
    """Convert a metric plan quantity to the cost library's unit."""
    if basis == "count":
        return quantity
    if basis == "area_m2":
        return quantity / M2_PER_ACRE if unit == "acre" else quantity / M2_PER_FT2 if unit == "sq ft" else quantity
    if basis == "length_m":
        return quantity * 3.28084 if unit == "linear foot" else quantity
    if basis == "volume_m3":
        return quantity * 264.172 if unit == "gallon" else quantity
    return quantity


def intervention_documents() -> list[dict]:
    """Catalog entries as knowledge-base documents, so the assistant's search finds them."""
    data = catalog()
    goals = {g["id"]: g["label"] for g in data["goals"]}
    phases = {p["id"]: p["label"] for p in data["phases"]}
    docs = []
    for i in data["interventions"]:
        serves = ", ".join(f"{goals[g].lower()}" for g, w in sorted(i["goals"].items(), key=lambda kv: -kv[1]))
        body = (f"{' '.join(i['summary'].split())}\n\nServes: {serves}. Phase: {phases[i['phase']]}. "
                f"Upkeep: {i['maintenance']}."
                + (f" NRCS practice codes: {', '.join(i['nrcs'])}." if i["nrcs"] else "")
                + ("\n\nCautions:\n" + "\n".join(f"- {c}" for c in i["cautions"]) if i["cautions"] else ""))
        docs.append({
            "source": "interventions", "doc_key": f"interventions:{i['id']}", "title": i["title"], "code": i["id"],
            "url": None, "body": body, "license": LICENSE, "commercial_ok": True, "version": str(data["version"]),
            "meta": {"topics": i["topics"], "category": i["category"], "phase": i["phase"], "goals": i["goals"],
                     "nrcs": i["nrcs"]},
        })
    return docs


BRIEF_FIELDS = ("goals", "setting", "has_buildings", "water_sources", "annual_rainfall_mm", "budget", "timeline",
                "maintenance", "constraints", "vision")


def brief_complete(brief: dict | None) -> bool:
    return bool(brief and brief.get("goals"))


def describe_reference_links(ids: list[str]) -> list[dict[str, Any]]:
    from .rules import load_references

    refs = {r["id"]: r for r in load_references()[1]}
    return [{"id": i, "title": refs[i]["title"], "url": refs[i].get("url"), "work_license": refs[i]["work_license"]}
            for i in ids if i in refs]
