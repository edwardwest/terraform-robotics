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
- **Along a contour:** when drawing any line (a hedgerow, path, swale-like water line, fence, brush berm), the bar at the bottom of the map switches between Freehand and **Along a contour** (needs a terrain model). Along a contour: click a start, then an end; the line follows the contour between them.
- **Rows on contour:** orchards, food forests, berries and creek-side plantings have **Rows: Straight / On contour**. On contour, rows run parallel to the contour through the middle of the area, as in keyline orchards, at the row spacing; plants sit along them at the plant spacing. The panel shows how many plants and rows that gives, and the map shows plant positions when zoomed in (Layers: "Show plant positions"). The sheet draws its trees from the same layout.
- **Zones and sectors** (panel under Layers): show zone rings (zones 1–4, default 50, 150, 400 and 1,000 ft from the house; zone 5 beyond) and sector wedges. The sun's path at the June and December solstices is computed from the site's latitude (where it rises and sets, and how high at noon). The person adds up to four winds (name and the direction each comes from) and the direction wildfire is most likely from (often uphill or the hot, dry fire-season wind; the local fire agency knows).
- **Checks** (panel under Zones and sectors; a selected feature shows its own): warnings and notes with their sources. Features outside the property; earthworks within 10 ft of the property line; animal enclosures within 100 ft of a well (California well standards); manure or compost uphill of water (with a terrain model; without one, only closeness); ponds on steep ground; roads over 16% grade (California fire-safe rules) and paths over 20%; plants within 5 ft of buildings and woodland within 30 ft of the house (CAL FIRE defensible space); no defensible space drawn; kitchen gardens or compost far from the house or garden; windbreaks running with a set wind. Clicking a check selects the feature. They're guidance, not approvals: counties set the rules.
- **Master plan sheet** (button under the Features list, or the Export step): an illustrated, printable plan. Settings save as they change and the preview updates: sheet size (11 × 17 or 24 × 36 in), title, address line, prepared by, base map (aerial photo, terrain shading, plain; the aerial photo falls back to terrain shading if it can't be loaded), contours, labels (callouts with leader lines, on the features, or off), which labels show, build phases, existing features, categories, the plant schedule and notes. Labels can be dragged on the preview; "Reset moved labels" puts them back. Download PDF gives the same drawing as the preview. Features with the same label share one callout. Tree symbols show the planting pattern; the schedule's plant counts come from the spacing settings.
- **3D view and fly-through** (button under the Features list): the plan on the terrain over the aerial photo. Drag to orbit, scroll to zoom. The year slider runs from Today (existing features only) to year 30: build phases appear in their start years (Phase start years, default 0, 2 and 4) and trees grow from nursery size toward their mature size. Sizes are estimates: a feature's own mature height, else the species' mature height and growth rate from USDA PLANTS, else a typical size for the type. Fly-through: frame a view, Add this view, repeat (up to 12), and set the seconds between views; Play glides through them and Record video saves an MP4 or WebM to your downloads. "Grow from today" grows the plan during the flight.
- Species data is uneven: about 2,000 of the 31,673 PLANTS taxa have full traits, and there's no cultivar or rootstock data, so an orchard's mature height is the person's to set.

**Decisions here**
- Which keypoint to design from, the grade, the spacing and the pattern. Parallel is the traditional choice and easiest to work with machinery; graded holds water movement more evenly on irregular land.
- Where swales help: usually across a valley above a keypoint, where they catch runoff from the catchment above.
- Whether keyline or swales belong in the plan at all: on small, flat or fire-first sites other interventions usually come first.

**Common problems**
- "Build the terrain first": there is no terrain model yet; go to the Survey step. The plan panel still works without it.
- Generate is disabled: no keypoint selected, the terrain is coarse, or the planning-grade draft box is unticked.

**When to move on:** once the design looks right, open the Estimate step.
