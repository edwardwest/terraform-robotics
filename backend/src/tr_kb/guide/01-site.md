# Step 1: Site ("Start with the land.")

**What it's for:** naming the property and setting the boundary everything else is computed inside.

**What's on screen**
- **Property name** and **Address** fields. Searching an address moves the map there.
- **Boundary source**, three ways to set the boundary:
  - **Import county parcel:** the recorded parcel line at the address you found. Sonoma County only for now. Button: "Import parcel".
  - **Draw it on the map:** click each corner, then edit vertices after.
  - **Upload a file:** a GeoJSON polygon in longitude and latitude.
- **Area** and **Perimeter** update as the boundary changes.
- **Continue to goals** saves the project. It stays disabled until there is a name ("Name the property to continue.") and a boundary ("Set a boundary to continue.").

**Decisions here**
- Which boundary to use. The terrain model, flow analysis, keypoints and estimate all stop at this line, so a boundary that cuts off the top of a valley loses the water that feeds it.

**Common problems**
- Parcel import fails outside Sonoma County: draw the boundary or upload a GeoJSON file instead.
- A parcel line that doesn't match the fences on the ground: draw the boundary you actually manage.

**When to move on:** once the boundary matches the land you plan to work, choose Continue to goals.
