"""AI design assistant (W9): Claude proposes layouts in plain language; the geometry engine computes every line.

The model never produces coordinates or quantities. It calls tools that read the site, search the knowledge
base, and ask the engine to compute keyline patterns and swales. Computed designs are saved as draft proposals
that a person previews on the map and accepts or discards.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable
from uuid import UUID

from fastapi import APIRouter, HTTPException
from shapely.geometry import Point

from tr_geo import design as geo
from tr_geo import project_geometry
from tr_kb import store as kb

from . import schemas
from .auth import CurrentUser
from .common import _project_or_404, layer_in, terrain_or_404, terrain_surface
from .db import execute, fetch_all, fetch_one, get_engine

router = APIRouter()

DEFAULT_MODEL = os.environ.get("ASSISTANT_MODEL", "claude-sonnet-5-5")
DESIGN_MODEL = os.environ.get("ASSISTANT_DESIGN_MODEL", "claude-opus-5-5")
MAX_TURNS = 8
DESIGN_WORDS = re.compile(r"\b(propose|design|layout|lay out|plan|pattern|keyline|swale|where should|compare)\b", re.I)

SYSTEM = """You are the design assistant in Terraform Robotics, a tool for regenerative water design on farms and ranches.
You help a designer read their site and lay out keyline patterns and swales.

How you work:
- Never invent coordinates, lengths, volumes, grades or costs. Every number you state comes from a tool result.
- Start from get_site_summary. Use search_knowledge for practice criteria and design rules, and cite them by title (and NRCS code) when you rely on them.
- To design, call propose_keyline_pattern or propose_swale. Each call computes real geometry from the terrain model and saves a draft the person sees on the map. Offer two or three options when the choice is genuinely open (for example parallel versus graded patterns, or different keypoints), then compare them on the numbers the tools return.
- Proposals are drafts. Say that the person can preview, accept or discard them in the panel. Do not claim anything has been built or saved to the design until they accept.
- Look at data quality. If the terrain is planning grade, say plainly that lines may be a metre or more off in the field and a drone LiDAR or RTK survey is needed for design grade. If it is coarse, do not propose keylines.
- Read the notes each tool returns (water toward the valley, steep fall, flow-path crossings, steep ground) and pass on the ones that matter.
- Talk in US units (feet, acres, gallons); tools use metres. 1 m = 3.281 ft; 1 acre = 4,047 m²; 1 m³ = 264.2 gal.
- Be concise and practical. Plain sentences, short lists where they help. No emoji."""

TOOLS: list[dict[str, Any]] = [
    {"name": "get_site_summary",
     "description": "Site facts: area, elevation range, mean slope, where water leaves, data-quality grade, keypoints (with elevation and whether confirmed), current design elements and the estimate total.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "propose_keyline_pattern",
     "description": "Compute a keyline through a keypoint and a rip pattern, and save it as a draft proposal for the person to preview. Returns lengths, line counts, area treated and design notes.",
     "input_schema": {"type": "object", "required": ["keypoint_id"], "properties": {
         "keypoint_id": {"type": "string", "description": "e.g. K1"},
         "grade": {"type": "number", "description": "fall per metre along the keyline, 0.002 (1:500) to 0.005 (1:200); default 0.00333 (1:300)"},
         "spacing_m": {"type": "number", "description": "rip line spacing in metres, 3 to 30; default 5"},
         "extent": {"type": "string", "enum": ["valley", "site"], "description": "keypoint's valley only, or the whole site"},
         "pattern": {"type": "string", "enum": ["parallel", "graded", "none"], "description": "parallel = Yeomans pattern (even spacing, grade drifts); graded = every line holds the grade"}}}},
    {"name": "propose_swale",
     "description": "Compute a dead-level swale on the contour that crosses a keypoint's valley a given height above (or below) the keypoint, and save it as a draft proposal. Returns length, storage, catchment and notes.",
     "input_schema": {"type": "object", "required": ["keypoint_id"], "properties": {
         "keypoint_id": {"type": "string"},
         "rise_m": {"type": "number", "description": "height above the keypoint along its valley (negative = below); default 0"},
         "half_length_m": {"type": "number", "description": "how far the swale runs along the contour each side of the valley, 20 to 300; default 80"},
         "width_m": {"type": "number", "description": "default 1.8"},
         "depth_m": {"type": "number", "description": "default 0.45"}}}},
    {"name": "get_estimate",
     "description": "The current cost estimate for the saved design (not drafts): line items, totals as low–high ranges, quantities.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "search_knowledge",
     "description": "Search NRCS conservation practice standards and the Terraform Robotics design rules. Returns passages with title, code and link.",
     "input_schema": {"type": "object", "required": ["query"], "properties": {
         "query": {"type": "string"}, "source": {"type": "string", "enum": ["nrcs_cps", "rules"]}}}},
    {"name": "find_species",
     "description": "Find plant species from USDA PLANTS by name and traits (growth habit, nitrogen fixing, drought tolerance, cold hardiness).",
     "input_schema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "name words, optional"},
         "growth_habit": {"type": "string", "description": "e.g. Tree, Shrub, Graminoid, Forb/herb"},
         "nitrogen_fixing": {"type": "boolean"},
         "drought_tolerance": {"type": "string", "description": "Low, Medium or High"},
         "min_temp_f_at_most": {"type": "number", "description": "species hardy to at least this cold (°F)"}}}},
]


# ---- Model client (Claude on Vertex AI) -------------------------------------------------------------


def _vertex_client():
    from anthropic import AnthropicVertex

    project = os.environ.get("GCP_PROJECT")
    if not project:
        raise HTTPException(503, "The assistant is not configured (no Google Cloud project).")
    return AnthropicVertex(project_id=project, region=os.environ.get("VERTEX_REGION", "global"))


client_factory: Callable[[], Any] = _vertex_client  # tests replace this


# ---- Tools -----------------------------------------------------------------------------------------


def _site_summary(project_id: UUID, project: dict) -> dict:
    t = terrain_or_404(project_id)
    s = t["summary"]
    kps = fetch_all(
        """SELECT properties FROM terrain_features WHERE project_id = :id AND layer = 'keypoints'
           ORDER BY properties->>'id'""", id=str(project_id))
    elements = fetch_all(
        """SELECT e.kind, e.label, e.params->>'keypoint_id' AS keypoint_id,
                  (SELECT count(*) FROM design_elements r WHERE r.group_id = e.group_id AND r.kind = 'rip') AS rips,
                  round(ST_Length(e.geom::geography)::numeric, 1) AS length_m, e.properties->>'storage_gal' AS storage_gal
           FROM design_elements e WHERE e.project_id = :id AND e.kind IN ('keyline', 'swale') ORDER BY e.kind, e.label""",
        id=str(project_id))
    q = s.get("quality", {})
    grade = "design" if q.get("design_pct", 0) >= 50 else "coarse" if q.get("coarse_pct", 0) >= 50 else "planning"
    return {
        "name": project["name"], "address": project.get("address"),
        "area_m2": round(float(project["area_m2"] or 0)),
        "elevation_min_m": s["elevation_min_m"], "elevation_max_m": s["elevation_max_m"],
        "mean_slope_pct": s["mean_slope_pct"], "water_leaves_toward": s["outlet_direction"],
        "main_valleys": s["main_valley_count"], "dem_resolution_m": s["dem_resolution_m"],
        "data_quality": q, "terrain_grade": grade,
        "keypoints": [{k: p.get(k) for k in ("id", "elevation_m", "confirmed", "gradient_above_pct", "gradient_below_pct", "score")}
                      for p in (r["properties"] for r in kps)],
        "design_elements": [{"kind": e["kind"], "label": e["label"], "keypoint_id": e["keypoint_id"],
                             "length_m": float(e["length_m"]), "rip_lines": int(e["rips"]) if e["kind"] == "keyline" else None,
                             "storage_gal": e["storage_gal"]} for e in elements],
    }


def _save_proposal(project_id: UUID, kind: str, params: dict, preview: dict, summary: dict) -> str:
    row = fetch_one(
        """INSERT INTO assistant_proposals (project_id, kind, params, preview, summary)
           VALUES (:pid, :kind, CAST(:params AS jsonb), CAST(:preview AS jsonb), CAST(:summary AS jsonb)) RETURNING id""",
        pid=str(project_id), kind=kind, params=json.dumps(params), preview=json.dumps(preview), summary=json.dumps(summary))
    return str(row["id"])


def _clamp(v, lo, hi, default):
    try:
        return min(max(float(v), lo), hi)
    except (TypeError, ValueError):
        return default


def _tool_propose_keyline(project_id: UUID, args: dict, allow_planning: bool) -> dict:
    from .design_api import plan_keyline

    body = schemas.KeylineCreate(
        keypoint_id=str(args.get("keypoint_id", "")), grade=_clamp(args.get("grade"), 0.002, 0.005, 1 / 300),
        spacing_m=_clamp(args.get("spacing_m"), 3, 30, 5.0), extent=args.get("extent") if args.get("extent") in ("valley", "site") else "valley",
        pattern=args.get("pattern") if args.get("pattern") in ("parallel", "graded", "none") else "graded",
        max_lines=200, allow_planning=allow_planning)
    plan = plan_keyline(project_id, body)
    pid = _save_proposal(project_id, "keyline", body.model_dump(), plan.preview, plan.summary)
    return {"proposal_id": pid, **plan.summary,
            "spacing_m": body.spacing_m, "grade": body.grade, "pattern": body.pattern, "extent": body.extent}


def _tool_propose_swale(project_id: UUID, args: dict, allow_planning: bool) -> dict:
    from .design_api import plan_swale

    t, surface, srid = terrain_surface(project_id)
    kp_id = str(args.get("keypoint_id", ""))
    kp_rows = layer_in(project_id, "keypoints", srid, "AND properties->>'id' = :kp", kp=kp_id)
    if not kp_rows:
        return {"error": f"Keypoint {kp_id} not found"}
    kp = kp_rows[0][0]
    valley = geo.valley_trunk(layer_in(project_id, "valleys", srid), kp)
    if valley is None:
        return {"error": "No valley line passes near this keypoint"}
    rise = _clamp(args.get("rise_m"), -50, 50, 0.0)
    center = kp if abs(rise) < 0.05 else geo.point_on_valley_at(surface, valley, kp, rise)
    if center is None:
        return {"error": f"The valley does not reach {rise:+.1f} m from the keypoint inside the terrain model"}
    try:
        a, b = geo.contour_span(surface, center, _clamp(args.get("half_length_m"), 20, 300, 80.0))
    except ValueError as e:
        return {"error": str(e)}
    to_ll = lambda xy: project_geometry(Point(xy), t["dem_crs"], "EPSG:4326")  # noqa: E731
    pa, pb = to_ll(a), to_ll(b)
    body = schemas.SwaleCreate(start=(pa.x, pa.y), end=(pb.x, pb.y), width_m=_clamp(args.get("width_m"), 0.5, 6, 1.8),
                               depth_m=_clamp(args.get("depth_m"), 0.15, 1.5, 0.45), berm=True, allow_planning=allow_planning)
    plan = plan_swale(project_id, body)
    preview = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "geometry": json.loads(json.dumps(plan.geom_ll.__geo_interface__)),
        "properties": {**plan.props, "kind": "swale", "label": "Proposed swale"}}]}
    summary = {k: plan.props.get(k) for k in ("elevation_m", "length_m", "width_m", "depth_m", "cut_volume_m3", "storage_gal",
                                               "catchment_m2", "terrain_slope_max_pct", "notes", "draft")}
    pid = _save_proposal(project_id, "swale", body.model_dump(), preview, {**summary, "keypoint_id": kp_id, "rise_m": rise})
    return {"proposal_id": pid, "keypoint_id": kp_id, "rise_m": rise, **summary}


KEY_TRAITS = ("growth_habit", "duration", "native_status", "nitrogen_fixation", "drought_tolerance", "shade_tolerance",
              "min_temp_f", "mature_height_ft", "moisture_use", "growth_rate", "precip_min_in", "precip_max_in")


def _key_traits(traits: dict) -> dict:
    picked = {k: traits[k] for k in KEY_TRAITS if k in traits}
    for k in traits:
        if len(picked) >= 16:
            break
        picked.setdefault(k, traits[k])
    return picked


def _float_or_none(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def run_tool(name: str, args: dict, project_id: UUID, project: dict, user: dict, allow_planning: bool) -> dict:
    try:
        if name == "get_site_summary":
            return _site_summary(project_id, project)
        if name == "propose_keyline_pattern":
            return _tool_propose_keyline(project_id, args, allow_planning)
        if name == "propose_swale":
            return _tool_propose_swale(project_id, args, allow_planning)
        if name == "get_estimate":
            from .outputs import build_estimate

            e = build_estimate(project_id, user, 15)
            return {k: e[k] for k in ("total_low", "total_high", "build_low", "build_high", "design_fee_low", "design_fee_high",
                                      "quantities", "draft")} | {"lines": [{k: ln[k] for k in ("label", "quantity", "unit", "total_low", "total_high")} for ln in e["lines"]]}
        if name == "search_knowledge":
            with get_engine().connect() as conn:
                hits = kb.search(conn, str(args.get("query", ""))[:300], limit=5, source=args.get("source"))
            return {"results": [{"title": h["title"], "code": h["code"], "heading": h["heading"], "url": h["url"],
                                 "license": h["license"], "text": h["body"][:1200]} for h in hits]}
        if name == "find_species":
            with get_engine().connect() as conn:
                rows = kb.find_species(conn, args.get("query"), growth_habit=args.get("growth_habit"),
                                       nitrogen_fixing=bool(args.get("nitrogen_fixing")),
                                       drought_tolerance=args.get("drought_tolerance"),
                                       min_temp_f_at_most=_float_or_none(args.get("min_temp_f_at_most")), limit=12)
            return {"species": [{"symbol": r["symbol"], "scientific_name": r["scientific_name"], "common_name": r["common_name"],
                                 "family": r["family"], "traits": _key_traits(r["traits"])} for r in rows],
                    "source": "USDA PLANTS (public domain)"}
        return {"error": f"Unknown tool {name}"}
    except HTTPException as e:
        return {"error": e.detail}
    except Exception as e:  # a bad argument or an engine failure is reported to the model, not raised
        return {"error": f"{type(e).__name__}: {str(e)[:300]}"}


# ---- Conversation loop -----------------------------------------------------------------------------


def converse(project_id: UUID, user: dict, messages: list[dict], allow_planning: bool) -> dict:
    project = _project_or_404(project_id, user)
    terrain_or_404(project_id)
    last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    model = DESIGN_MODEL if DESIGN_WORDS.search(last_user) else DEFAULT_MODEL
    client = client_factory()
    convo: list[dict] = [{"role": m["role"], "content": m["content"]} for m in messages]
    system = [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}]
    tool_log, proposal_ids, citations = [], [], []
    reply = ""
    for _ in range(MAX_TURNS):
        try:
            resp = client.messages.create(model=model, max_tokens=2048, system=system, tools=TOOLS, messages=convo)
        except Exception as e:
            import anthropic

            if isinstance(e, anthropic.APIStatusError) and e.status_code in (429, 529):
                raise HTTPException(503, "The assistant is busy right now. Try again in a minute.")
            if isinstance(e, anthropic.APIError):
                raise HTTPException(502, f"The assistant could not answer: {str(e)[:200]}")
            raise
        blocks = [b.model_dump(exclude_none=True) if hasattr(b, "model_dump") else dict(b) for b in resp.content]
        convo.append({"role": "assistant", "content": blocks})
        uses = [b for b in blocks if b.get("type") == "tool_use"]
        reply = "\n".join(b["text"] for b in blocks if b.get("type") == "text").strip()
        if resp.stop_reason != "tool_use" or not uses:
            break
        results = []
        for u in uses:
            out = run_tool(u["name"], u.get("input") or {}, project_id, project, user, allow_planning)
            if "proposal_id" in out:
                proposal_ids.append(out["proposal_id"])
            for r in out.get("results", []) if u["name"] == "search_knowledge" else []:
                if r["title"] not in [c["title"] for c in citations]:
                    citations.append({"title": r["title"], "url": r["url"], "code": r["code"]})
            tool_log.append({"tool": u["name"], "input": u.get("input") or {}, "error": out.get("error")})
            result = {"type": "tool_result", "tool_use_id": u["id"], "content": json.dumps(out, default=str)[:20000]}
            if out.get("error"):
                result["is_error"] = True
            results.append(result)
        convo.append({"role": "user", "content": results})
    else:
        reply = reply or "I ran out of steps before finishing. Ask me to continue."
    proposals = proposals_by_id(project_id, proposal_ids)
    return {"reply": reply, "model": model, "tool_log": tool_log, "proposals": proposals, "citations": citations}


def proposals_by_id(project_id: UUID, ids: list[str]) -> list[dict]:
    if not ids:
        return []
    return fetch_all(
        """SELECT id::text AS id, kind, params, preview, summary, status, created_at FROM assistant_proposals
           WHERE project_id = :pid AND id = ANY(CAST(:ids AS uuid[])) ORDER BY created_at""",
        pid=str(project_id), ids=ids)


def list_proposals_rows(project_id: UUID, status: str | None = None) -> list[dict]:
    rows = fetch_all(
        """SELECT id::text AS id, kind, params, preview, summary, status, created_at FROM assistant_proposals
           WHERE project_id = :pid """ + ("AND status = :status " if status else "") + "ORDER BY created_at DESC LIMIT 30",
        pid=str(project_id), **({"status": status} if status else {}))
    return rows


# ---- Routes ----------------------------------------------------------------------------------------


@router.post("/api/projects/{project_id}/assistant", response_model=schemas.AssistantReply)
def assistant(project_id: UUID, body: schemas.AssistantRequest, user: CurrentUser):
    return converse(project_id, user, [m.model_dump() for m in body.messages], body.allow_planning)


@router.get("/api/projects/{project_id}/assistant/proposals", response_model=list[schemas.Proposal])
def proposals(project_id: UUID, user: CurrentUser, status: str | None = "draft"):
    _project_or_404(project_id, user)
    return list_proposals_rows(project_id, status)


@router.post("/api/projects/{project_id}/assistant/proposals/{proposal_id}/accept", response_model=schemas.Proposal)
def accept_proposal(project_id: UUID, proposal_id: UUID, user: CurrentUser):
    from .design_api import plan_keyline, plan_swale, save_keyline, save_swale

    _project_or_404(project_id, user)
    # claim the draft first, so two clicks (or two tabs) can never save it twice
    p = fetch_one(
        """UPDATE assistant_proposals SET status = 'accepted' WHERE id = :id AND project_id = :pid AND status = 'draft'
           RETURNING kind, params""", id=str(proposal_id), pid=str(project_id))
    if not p:
        cur = fetch_one("SELECT status FROM assistant_proposals WHERE id = :id AND project_id = :pid",
                        id=str(proposal_id), pid=str(project_id))
        raise HTTPException(409 if cur else 404, f"Proposal is already {cur['status']}" if cur else "Proposal not found")
    try:
        # recompute from the stored parameters so what is saved always matches the current terrain model
        if p["kind"] == "keyline":
            body = schemas.KeylineCreate(**p["params"])
            save_keyline(project_id, body.keypoint_id, plan_keyline(project_id, body))
        else:
            save_swale(project_id, plan_swale(project_id, schemas.SwaleCreate(**p["params"])))
    except Exception:
        execute("UPDATE assistant_proposals SET status = 'draft' WHERE id = :id", id=str(proposal_id))
        raise
    return proposals_by_id(project_id, [str(proposal_id)])[0]


@router.post("/api/projects/{project_id}/assistant/proposals/{proposal_id}/discard", status_code=204)
def discard_proposal(project_id: UUID, proposal_id: UUID, user: CurrentUser):
    _project_or_404(project_id, user)
    row = fetch_one(
        """UPDATE assistant_proposals SET status = 'discarded' WHERE id = :id AND project_id = :pid AND status = 'draft'
           RETURNING id""", id=str(proposal_id), pid=str(project_id))
    if not row:
        raise HTTPException(404, "No draft proposal with that id")
