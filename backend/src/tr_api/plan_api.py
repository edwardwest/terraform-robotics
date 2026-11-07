"""Goals brief, intervention ideas and the plan.

The brief records what the person wants from the land. Ideas are catalog interventions ranked against the brief
and the site by `tr_kb.interventions` (plain code, no model). The plan is the interventions the person chose, in
build order; those without a design tool carry a planning allowance into the estimate.
"""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, HTTPException

from tr_kb import interventions as iv

from . import schemas
from .auth import CurrentUser
from .common import _project_or_404
from .db import execute, fetch_all, fetch_one

router = APIRouter()


# ---- Shared with the assistant and the estimate ---------------------------------------------------


def get_brief(project_id: UUID) -> dict:
    row = fetch_one("SELECT brief, updated_at FROM project_briefs WHERE project_id = :id", id=str(project_id))
    if not row:
        return {"updated_at": None}
    return {**{k: v for k, v in row["brief"].items() if k in iv.BRIEF_FIELDS}, "updated_at": row["updated_at"]}


def save_brief(project_id: UUID, update: dict) -> dict:
    """Merge the fields given into the stored brief. A field set to null clears it."""
    current = {k: v for k, v in get_brief(project_id).items() if k != "updated_at"}
    merged = {k: v for k, v in {**current, **update}.items() if v is not None and v != [] and v != ""}
    execute(
        """INSERT INTO project_briefs (project_id, brief, updated_at) VALUES (:id, CAST(:b AS jsonb), now())
           ON CONFLICT (project_id) DO UPDATE SET brief = EXCLUDED.brief, updated_at = now()""",
        id=str(project_id), b=json.dumps(merged))
    return get_brief(project_id)


def site_facts(project_id: UUID, project: dict) -> dict:
    """The site facts the recommender uses: area always, slope and valleys once the terrain model exists."""
    facts = {"area_m2": round(float(project["area_m2"] or 0)) or None, "has_terrain": False}
    t = fetch_one("SELECT summary FROM terrain_results WHERE project_id = :id", id=str(project_id))
    if t:
        s = t["summary"]
        q = s.get("quality", {})
        facts.update({
            "has_terrain": True, "mean_slope_pct": s.get("mean_slope_pct"), "main_valleys": s.get("main_valley_count"),
            "keypoint_count": s.get("keypoint_count"),
            "terrain_grade": "design" if q.get("design_pct", 0) >= 50 else "coarse" if q.get("coarse_pct", 0) >= 50 else "planning",
        })
    return facts


def plan_rows(project_id: UUID) -> list[dict]:
    rows = {r["intervention_id"]: r for r in fetch_all(
        "SELECT intervention_id, quantity, notes, created_at FROM project_plan WHERE project_id = :id", id=str(project_id))}
    out = []
    for item in iv.sequence(list(rows)):
        r = rows[item["id"]]
        out.append({"intervention_id": item["id"], "title": item["title"], "category": item["category"],
                    "phase": item["phase"], "tool": item["tool"],
                    "quantity_basis": (item["quantity"] or {}).get("basis"), "quantity": r["quantity"],
                    "notes": r["notes"], "cost_item": item["cost_item"], "created_at": r["created_at"]})
    return out


def recommendations(project_id: UUID, project: dict) -> dict:
    brief = get_brief(project_id)
    site = site_facts(project_id, project)
    selected = {r["intervention_id"] for r in fetch_all(
        "SELECT intervention_id FROM project_plan WHERE project_id = :id", id=str(project_id))}
    items = iv.recommend(brief, site, selected)
    for r in items:
        r["references"] = iv.describe_reference_links(r["references"])
    return {"brief_complete": iv.brief_complete(brief), "site": site, "items": items}


# ---- Routes ----------------------------------------------------------------------------------------


@router.get("/api/interventions/catalog")
def intervention_catalog(user: CurrentUser):
    """Goals, phases, categories, brief answer options and the intervention catalog, for the web app's labels."""
    data = iv.catalog()
    return {
        "version": str(data["version"]), "goals": data["goals"], "phases": data["phases"],
        "categories": data["categories"], "questions": data["questions"],
        "interventions": [{k: i[k] for k in ("id", "title", "category", "phase", "maintenance", "cost_tier", "tool",
                                             "quantity", "nrcs")} | {"summary": " ".join(i["summary"].split())}
                          for i in data["interventions"]],
    }


@router.get("/api/projects/{project_id}/brief", response_model=schemas.Brief)
def read_brief(project_id: UUID, user: CurrentUser):
    _project_or_404(project_id, user)
    return get_brief(project_id)


@router.put("/api/projects/{project_id}/brief", response_model=schemas.Brief)
def update_brief(project_id: UUID, body: schemas.BriefUpdate, user: CurrentUser):
    """Merge: fields left out are kept; fields sent as null are cleared."""
    _project_or_404(project_id, user)
    return save_brief(project_id, body.model_dump(exclude_unset=True))


@router.get("/api/projects/{project_id}/recommendations", response_model=schemas.Recommendations)
def read_recommendations(project_id: UUID, user: CurrentUser):
    project = _project_or_404(project_id, user)
    return recommendations(project_id, project)


@router.get("/api/projects/{project_id}/plan", response_model=list[schemas.PlanItem])
def read_plan(project_id: UUID, user: CurrentUser):
    _project_or_404(project_id, user)
    return plan_rows(project_id)


@router.put("/api/projects/{project_id}/plan/{intervention_id}", response_model=schemas.PlanItem)
def put_plan_item(project_id: UUID, intervention_id: str, body: schemas.PlanItemUpdate, user: CurrentUser):
    """Add an intervention to the plan, or update its quantity and notes. Quantity defaults to the catalog's."""
    _project_or_404(project_id, user)
    item = iv.by_id().get(intervention_id)
    if not item:
        raise HTTPException(404, "Unknown intervention")
    fields = body.model_dump(exclude_unset=True)
    default_qty = (item["quantity"] or {}).get("default")
    execute(
        """INSERT INTO project_plan (project_id, intervention_id, quantity, notes)
           VALUES (:pid, :iid, :qty, :notes)
           ON CONFLICT (project_id, intervention_id) DO UPDATE SET
             quantity = CASE WHEN :set_qty THEN EXCLUDED.quantity ELSE project_plan.quantity END,
             notes = CASE WHEN :set_notes THEN EXCLUDED.notes ELSE project_plan.notes END,
             updated_at = now()""",
        pid=str(project_id), iid=intervention_id,
        qty=fields.get("quantity", default_qty) if item["quantity"] else None, notes=fields.get("notes"),
        set_qty="quantity" in fields and bool(item["quantity"]), set_notes="notes" in fields)
    return next(r for r in plan_rows(project_id) if r["intervention_id"] == intervention_id)


@router.delete("/api/projects/{project_id}/plan/{intervention_id}", status_code=204)
def delete_plan_item(project_id: UUID, intervention_id: str, user: CurrentUser):
    _project_or_404(project_id, user)
    execute("DELETE FROM project_plan WHERE project_id = :pid AND intervention_id = :iid",
            pid=str(project_id), iid=intervention_id)
