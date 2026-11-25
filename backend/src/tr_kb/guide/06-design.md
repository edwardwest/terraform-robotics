# Step 6: Design ("Put the plan on the land.")

**What it's for:** seeing the plan in build order, laying out the interventions the app computes from the terrain model (keyline patterns and swales, in **Earthworks** mode), and drawing everything else on a **Master plan** (the second mode). Keylines and swales are computed from the terrain model, never drawn by hand.

**What's on screen**
- **Your plan:** the interventions chosen on the Ideas step, in build order after P.A. Yeomans' scale of permanence (water, access, trees, buildings, fencing, soil). Keyline and swale entries have **Lay out**, which opens the matching tool below. Other entries show their quantity and are carried into the estimate as planning allowances. **Edit plan** returns to the Ideas step.
- Two modes: **Keyline pattern** and **Swale on contour**.
- **Keyline pattern** settings:
  - **Keypoint:** which keypoint the keyline starts from. A dot marks a keypoint not yet confirmed on the Terrain step. Clicking a keypoint on the map selects it.
  - **Grade off contour:** the gentle fall along the keyline, shown as 1:N (for example 1:300).
  - **Rip spacing (ft)** between rip lines.
  - **Extent:** Keypoint valley or Whole site.
  - **Pattern:** Parallel to keyline (the classic Yeomans pattern; even spacing, so the grade drifts on lines further away) or Each line graded (every line holds the grade; spacing varies with the land).
  - **Generate pattern** (or Regenerate pattern) computes it.
- **Swale on contour** settings: Width (ft), Depth (ft), Berm on the downhill side. **Place swale**, then click the start and the end on the map; the swale is dead level along the contour.
- **Design elements** lists what's saved; selecting a line on the map shows its **Line profile** below the map.
- **Pattern** totals: lines, total rip line, area treated, and the build estimate.
- On planning-grade terrain, a **Draft on planning-grade terrain** checkbox must be ticked to design; lines may sit a metre or more off in the field and exports are marked draft. Coarse terrain is refused.
- **Assistant proposals** appear dashed on the map with Preview, Accept and Discard. Only Accept adds them to the design.

**Master plan mode** (the Master plan chip at the top of the step)
- **To place, from your plan:** chosen interventions not yet drawn. Clicking one starts drawing it with the right shape.
- **Feature library:** nine categories with map colors: Water, Annual crops, Trees and perennials, Habitat, Animals, Structures, Access, Energy and cycling, Fire safety. Each type is drawn as a point (a cistern, a coop), a line (a windbreak, a road, a fence) or an area (a pond, an orchard, a house). Points: click once. Lines: click along, then click the last point again. Areas: click around, then click the first point to close. Escape cancels.
- Selecting a feature (on the map or in the **Features** list) opens its properties: type, label, **Status** (Proposed or Existing), **Build phase** (1 to 3), measurements, and the settings its type takes: a **species list** from USDA PLANTS with row and plant spacing and mature height (the app counts the plants), building height and roof, or storage capacity in gallons. **Edit shape** lets the person drag corners or the whole shape, then **Save shape**.
- **Layers:** show or hide categories, show build phases cumulatively (Phase 1, Phases 1–2, all), and show or hide existing features.
- Proposed features that place a plan intervention are measured (area, length or count) and that measurement replaces the planning allowance in the estimate. Existing features are shown but not priced.
- Without a terrain model the master plan still works; the map shows the property line only.
- **Master plan sheet** (button under the Features list, or the Export step): an illustrated, printable plan. Settings save as they change and the preview updates: sheet size (11 × 17 or 24 × 36 in), title, address line, prepared by, base map (aerial photo, terrain shading, plain; the aerial photo falls back to terrain shading if it can't be loaded), contours, labels (callouts with leader lines, on the features, or off), which labels show, build phases, existing features, categories, the plant schedule and notes. Labels can be dragged on the preview; "Reset moved labels" puts them back. Download PDF gives the same drawing as the preview. Features with the same label share one callout. Tree symbols show the planting pattern; the schedule's plant counts come from the spacing settings.
- Species data is uneven: about 2,000 of the 31,673 PLANTS taxa have full traits, and there's no cultivar or rootstock data, so an orchard's mature height is the person's to set.

**Decisions here**
- Which keypoint to design from, the grade, the spacing and the pattern. Parallel is the traditional choice and easiest to work with machinery; graded holds water movement more evenly on irregular land.
- Where swales help: usually across a valley above a keypoint, where they catch runoff from the catchment above.
- Whether keyline or swales belong in the plan at all: on small, flat or fire-first sites other interventions usually come first.

**Common problems**
- "Build the terrain first": there is no terrain model yet; go to the Survey step. The plan panel still works without it.
- Generate is disabled: no keypoint selected, the terrain is coarse, or the planning-grade draft box is unticked.

**When to move on:** once the design looks right, open the Estimate step.
