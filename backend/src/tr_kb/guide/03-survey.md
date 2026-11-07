# Step 3: Survey ("Bring the best ground data you have.")

**What it's for:** collecting elevation data and building the terrain model the rest of the app works from.

**What's on screen**
- Source cards:
  - **USGS 3DEP:** free public elevation for the United States at the best available resolution. Button: "Fetch public elevation".
  - **Drone LiDAR upload:** a point cloud from a drone flight, LAS or LAZ, any size.
  - **Old survey or drawing:** a DEM as GeoTIFF, or contour lines as GeoJSON with an elevation attribute.
  - **Phone LiDAR scan:** coming soon.
- **Data quality** panel: how much of the site is **Design grade** (1 m or finer), **Planning grade** (up to 10 m) and **Too coarse** (over 10 m), the finest cell, and the sources used. The shares appear once the terrain model is built.
- **Build terrain model** starts the terrain job. It needs at least one source ("Add at least one source to continue."). Progress shows while it runs, then the Terrain step opens with the results.

**How to read data quality**
- Design grade over half the site: keylines and swales can be laid out for the field.
- Mostly planning grade: designs are allowed as drafts only, marked draft on every export, and may sit a metre or more off in the field.
- Mostly coarse: the app will not lay out keylines. Add better data.
- Public 3DEP data is often planning grade in rural areas. A drone LiDAR flight or an RTK survey is the usual way to reach design grade.

**When to move on:** after the terrain model finishes building. Rebuild it whenever better data is added.
