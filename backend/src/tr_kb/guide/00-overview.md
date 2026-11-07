# How Terraform Robotics works

Terraform Robotics takes a piece of land from a boundary to a costed water design in five steps, shown across the top of every project page: 1 Site, 2 Survey, 3 Terrain, 4 Design, 5 Estimate. Export is reached from the Estimate step.

1. **Site:** name the property and set its boundary.
2. **Survey:** bring ground elevation data and build the terrain model.
3. **Terrain:** read contours, flow paths, valleys and ridges, and confirm the keypoints that anchor the design.
4. **Design:** lay out keyline patterns and swales. Every line is computed from the terrain model, never drawn by hand.
5. **Estimate:** see what the design costs to build, then export plans for the field.

Things that hold on every step:
- The app measures in feet, acres and gallons on screen; the engine works in metres underneath.
- Data quality limits what the app will do. Design grade (1 m cells or finer) supports field-ready design. Planning grade (up to 10 m) supports drafts that are clearly marked as drafts and may sit a metre or more off in the field. Coarse data is refused for keylines.
- The assistant can explain, coach and, on the Design step, propose keyline patterns and swales. Its proposals stay drafts until the person clicks Accept. It cannot confirm keypoints, change the boundary or save anything on its own.
