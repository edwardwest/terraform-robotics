# How Terraform Robotics works

Terraform Robotics takes a piece of land from a boundary and a set of goals to a costed regenerative plan in seven steps, shown across the top of every project page: 1 Site, 2 Goals, 3 Survey, 4 Terrain, 5 Ideas, 6 Design, 7 Estimate. Export is reached from the Estimate step.

1. **Site:** name the property and set its boundary.
2. **Goals:** say what you want from the land (water, food, fire safety, soil, habitat, animals and more), your budget, how much upkeep you want, and what limits you. The assistant can talk it through with you.
3. **Survey:** bring ground elevation data and build the terrain model.
4. **Terrain:** read contours, flow paths, valleys and ridges, and confirm keypoints.
5. **Ideas:** interventions from the catalog (water harvesting, earthworks, soil, plants and trees, fire, animals, structures and access) ranked against your goals and your site. Add the ones you want to your plan.
6. **Design:** your plan in build order, and the tools that compute keyline patterns and swales from the terrain model.
7. **Estimate:** what the design and the plan cost to build, then export plans for the field.

Things that hold on every step:
- The app measures in feet, acres, gallons and inches on screen; the engine works in metres underneath.
- Goals come first: the Ideas step ranks interventions by the goals brief. Keyline and swales are suggested only where the land and the goals call for them.
- Ideas can be explored before the terrain model exists; checks that depend on slope and valleys say so until it is built.
- Data quality limits what the design tools will do. Design grade (1 m cells or finer) supports field-ready design. Planning grade (up to 10 m) supports drafts that are clearly marked as drafts and may sit a metre or more off in the field. Coarse data is refused for keylines.
- The assistant can explain, coach, interview you about your goals and suggest brief answers (you apply them), rank ideas, and, on the Design step, propose keyline patterns and swales. Its proposals stay drafts until the person clicks Accept. It cannot confirm keypoints, change the boundary, add to the plan or save anything on its own.
