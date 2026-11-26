"""How big plants get and how fast, for the 3D view's year slider. Pure.

USDA PLANTS gives a mature height (ft) and a growth rate (Rapid, Moderate, Slow) for some species, not years to
maturity, so years come from the growth rate by rule of thumb, and types fall back to typical values. The 3D view
labels these as estimates. A person's own mature height on the feature wins over the data.
"""

from __future__ import annotations

FT = 0.3048

# Years from planting to roughly full size, by PLANTS growth rate.
YEARS_BY_RATE = {"rapid": 5, "moderate": 10, "slow": 18}

# Typical (height m, canopy diameter m, years to full size) by feature type, when neither the person nor the data says.
TYPE_DEFAULTS = {
    "orchard": (5.0, 4.0, 7),
    "food-forest": (6.0, 4.5, 10),
    "berries": (1.8, 1.5, 3),
    "shade-tree": (12.0, 9.0, 15),
    "windbreak": (10.0, 4.0, 10),
    "hedgerow": (3.0, 2.0, 5),
    "existing-forest": (18.0, 9.0, 0),
    "riparian": (8.0, 5.0, 8),
    "meadow": (0.6, 0.0, 1),
}


def mature_size(ftype: str, props: dict, traits: list[dict], type_defaults: dict | None = None) -> tuple[float, float, int]:
    """(height m, canopy diameter m, years to full size) for a planted feature: the feature's own height, else the
    tallest listed species with data, else the type's typical size. A height equal to the library default (copied in
    when the feature was drawn) doesn't count as the person's own. Canopy scales with height and is kept within the
    spacing, so neighbours touch rather than overlap."""
    h0, c0, y0 = TYPE_DEFAULTS.get(ftype, (5.0, 4.0, 8))
    heights = [float(t["height_ft_mature"]) * FT for t in traits if _num(t.get("height_ft_mature"))]
    rates = [str(t.get("growth_rate", "")).lower() for t in traits if t.get("growth_rate")]
    own = props.get("height_m")
    if own and type_defaults and own == type_defaults.get("height_m") and heights:
        own = None
    height = float(own) if own else (max(heights) if heights else h0)
    years = y0
    if rates:
        years = max(YEARS_BY_RATE.get(r, y0) for r in rates)  # the slowest listed species sets the pace
    canopy = c0 * (height / h0) if h0 else c0
    spacing = props.get("plant_spacing_m")
    if spacing:
        canopy = min(canopy, float(spacing) * 1.05)
    return round(height, 2), round(max(canopy, 0.4), 2), int(years)


def size_at(age_years: float, years_to_mature: int, height: float, canopy: float) -> tuple[float, float] | None:
    """Height and canopy at an age; None before planting. Growth is quick at first and levels off (a simple
    saturating curve), starting from a nursery-sized plant."""
    if age_years < 0:
        return None
    if years_to_mature <= 0:
        return height, canopy
    f = min(1.0, 0.15 + 0.85 * (1 - (1 - min(age_years / years_to_mature, 1.0)) ** 1.6))
    return round(height * f, 2), round(canopy * f, 2)


def _num(v) -> bool:
    try:
        return float(v) > 0
    except (TypeError, ValueError):
        return False
