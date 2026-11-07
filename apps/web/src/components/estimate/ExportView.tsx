"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, exportUrl, type DesignCollection, type Project } from "@/lib/api";
import { IconAlert, IconArrowLeft, IconDownload } from "../Icons";
import { useAssistantPage } from "@/lib/assistant";
import styles from "./Estimate.module.css";

type GisFormat = "geojson" | "shapefile" | "kml";

export function ExportView({ projectId }: { projectId: string }) {
  const [project, setProject] = useState<Project | null>(null);
  const [design, setDesign] = useState<DesignCollection | null>(null);
  const [gis, setGis] = useState<GisFormat>("geojson");
  const [guidance, setGuidance] = useState<"geojson" | "shapefile">("shapefile");
  const [error, setError] = useState<string | null>(null);

  useAssistantPage("estimate", {
    page: "Export (reached from the Estimate step)",
    design_elements: design ? design.features.length : null,
    gis_format: gis,
    tractor_path_format: guidance,
  });

  useEffect(() => {
    api.getProject(projectId).then(setProject).catch((e: Error) => setError(e.message));
    api.getDesign(projectId).then(setDesign).catch((e: Error) => setError(e.message));
  }, [projectId]);

  const feats = design?.features ?? [];
  const lines = feats.filter((f) => f.properties.kind !== "swale").length;
  const draft = feats.some((f) => f.properties.draft);
  const empty = design !== null && feats.length === 0;
  const gisHref = gis === "geojson" ? exportUrl.geojson(projectId) : gis === "shapefile" ? exportUrl.shapefile(projectId) : exportUrl.kml(projectId);

  return (
    <div className={styles.exportLayout}>
      <header className={styles.head}>
        <p className="app-eyebrow">{project ? `${project.name} · ` : ""}Export</p>
        <h1 className="app-display">Take the design into the field.</h1>
        <p className="app-body">One design, several ways out: a plan set for people, files for GIS and CAD, and paths for machines.</p>
        {draft && <p className={`app-small ${styles.draft}`}><IconAlert size={12} /> The design is a draft on planning-grade terrain; every export says so.</p>}
        {empty && <p className="app-body">Nothing to export yet. <Link href={`/projects/${projectId}/design`}>Lay out the design</Link> first.</p>}
        {error && <p className="error-text" role="alert">{error}</p>}
      </header>

      <div className={styles.cards}>
        <section className={`card ${styles.exportCard}`}>
          <p className="app-eyebrow">PDF plan set</p>
          <h2 className="app-h2">11 × 17 sheets</h2>
          <ul className="app-small">
            <li>Keyline and rip layout sheet with legend, scale and north arrow</li>
            <li>Swale and keyline schedules</li>
            <li>Estimate summary</li>
          </ul>
          <a className={`btn btn-primary ${empty ? styles.off : ""}`} href={exportUrl.pdf(projectId)} download><IconDownload size={16} /> Download PDF</a>
        </section>

        <section className={`card ${styles.exportCard}`}>
          <p className="app-eyebrow">GIS files</p>
          <h2 className="app-h2">Georeferenced layers</h2>
          <p className="app-small">Keylines, rip lines, swales, keypoints and the property line, in longitude and latitude.</p>
          <div className={styles.inline}>
            {(["geojson", "shapefile", "kml"] as const).map((f) => (
              <button key={f} type="button" className="chip" aria-pressed={gis === f} onClick={() => setGis(f)}>
                {f === "geojson" ? "GeoJSON" : f === "shapefile" ? "Shapefile" : "KML"}
              </button>
            ))}
          </div>
          <a className={`btn ${empty ? styles.off : ""}`} href={gisHref} download><IconDownload size={16} /> Download</a>
        </section>

        <section className={`card ${styles.exportCard}`}>
          <p className="app-eyebrow">CAD drawing</p>
          <h2 className="app-h2">DXF</h2>
          <p className="app-small">Each element on its own layer, with contours at their elevations. Site coordinates: UTM, metres.</p>
          <p className="app-small">Layers: BOUNDARY, KEYLINE, RIP, SWALE, BERM, CONTOUR, CONTOUR_INDEX, KEYPOINT</p>
          <a className={`btn ${empty ? styles.off : ""}`} href={exportUrl.dxf(projectId)} download><IconDownload size={16} /> Download DXF</a>
        </section>

        <section className={`card ${styles.exportCard}`}>
          <p className="app-eyebrow">GPS tractor paths</p>
          <h2 className="app-h2">{lines} guidance lines</h2>
          <p className="app-small">One line per rip pass, top of the slope first, alternating direction to cut turns. Shapefile imports into most guidance displays.</p>
          <div className={styles.inline}>
            {(["shapefile", "geojson"] as const).map((f) => (
              <button key={f} type="button" className="chip" aria-pressed={guidance === f} onClick={() => setGuidance(f)}>
                {f === "geojson" ? "GeoJSON" : "Shapefile"}
              </button>
            ))}
          </div>
          <a className={`btn ${lines ? "" : styles.off}`} href={exportUrl.guidance(projectId, guidance)} download><IconDownload size={16} /> Download paths</a>
        </section>

        <section className={`card ${styles.exportCard} ${styles.muted}`}>
          <p className="app-eyebrow">Autonomous keyline robot</p>
          <h2 className="app-h2">Coming.</h2>
          <p className="app-small">Send the design straight to the Terraform Robotics solar keyline robot.</p>
          <button type="button" className="btn" disabled>Not available yet</button>
        </section>
      </div>

      <footer className={styles.foot}>
        <Link href={`/projects/${projectId}/estimate`} className="btn btn-ghost"><IconArrowLeft /> Back to estimate</Link>
      </footer>
    </div>
  );
}
