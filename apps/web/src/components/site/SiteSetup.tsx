"use client";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Polygon } from "geojson";
import { api, type BoundarySource, type GeocodeResult, type Parcel } from "@/lib/api";
import { extractPolygon, polygonAreaM2, polygonPerimeterM } from "@/lib/geo";
import { formatAcres, formatMiles } from "@/lib/units";
import { IconArrowRight, IconUpload } from "../Icons";
import { useAssistantPage } from "@/lib/assistant";
import styles from "./SiteSetup.module.css";

const BoundaryMap = dynamic(() => import("../BoundaryMap").then((m) => m.BoundaryMap), {
  ssr: false,
  loading: () => <div className={styles.mapLoading} aria-hidden="true" />,
});

type Source = "parcel" | "upload" | "drawn";

/** "38.40, -122.80" or "-122.80, 38.40" style coordinates typed into the address field. */
function parseCoords(s: string): [number, number] | null {
  const m = s.trim().match(/^(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)$/);
  if (!m) return null;
  const a = parseFloat(m[1]);
  const b = parseFloat(m[2]);
  if (Math.abs(a) <= 90 && Math.abs(b) <= 180) return [b, a]; // lat, lng
  if (Math.abs(b) <= 90 && Math.abs(a) <= 180) return [a, b]; // lng, lat
  return null;
}

export function SiteSetup({ projectId }: { projectId: string | null }) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [source, setSource] = useState<Source>("drawn");
  const [boundary, setBoundary] = useState<Polygon | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(!!projectId);
  const [flyTo, setFlyTo] = useState<{ center: [number, number]; zoom: number } | null>(null);
  const [candidates, setCandidates] = useState<GeocodeResult[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [pin, setPin] = useState<[number, number] | null>(null);
  const [parcel, setParcel] = useState<Parcel | null>(null);
  const [parcelBusy, setParcelBusy] = useState(false);
  const [parcelError, setParcelError] = useState<string | null>(null);
  const loadedBoundary = useRef<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!projectId) return;
    api
      .getProject(projectId)
      .then((p) => {
        setName(p.name);
        setAddress(p.address ?? "");
        setBoundary(p.boundary);
        loadedBoundary.current = JSON.stringify(p.boundary);
        setSource(p.boundary_source === "upload" ? "upload" : p.boundary_source === "parcel" ? "parcel" : "drawn");
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [projectId]);

  const area = useMemo(() => polygonAreaM2(boundary), [boundary]);

  useAssistantPage("site", {
    property_name_set: !!name.trim(),
    address_set: !!address.trim(),
    boundary_source_selected: source === "parcel" ? "Import county parcel" : source === "drawn" ? "Draw it on the map" : "Upload a file",
    boundary_set: !!boundary,
    area_m2: boundary && area != null ? Math.round(area) : null,
    errors: [error, fileError, parcelError, searchError].filter(Boolean),
  });
  const perimeter = useMemo(() => polygonPerimeterM(boundary), [boundary]);

  const onFile = async (file: File | undefined) => {
    setFileError(null);
    if (!file) return;
    setFileName(file.name);
    try {
      const text = await file.text();
      const poly = extractPolygon(JSON.parse(text));
      setBoundary(poly);
    } catch (e) {
      setFileError(e instanceof SyntaxError ? "That file is not valid GeoJSON." : (e as Error).message);
    }
  };

  const goTo = (c: [number, number]) => {
    setPin(c);
    setFlyTo({ center: c, zoom: 16 });
  };

  const findAddress = async () => {
    setSearchError(null);
    const c = parseCoords(address);
    if (c) {
      setCandidates(null);
      goTo(c);
      return;
    }
    if (address.trim().length < 3) return;
    setSearching(true);
    try {
      const results = await api.geocode(address.trim());
      setCandidates(results);
      if (results.length === 1) goTo([results[0].lng, results[0].lat]);
      if (!results.length) setSearchError("No match. Try the street address with city, or type latitude, longitude.");
    } catch (e) {
      setSearchError((e as Error).message);
    } finally {
      setSearching(false);
    }
  };

  const importParcel = async () => {
    if (!pin) return;
    setParcelBusy(true);
    setParcelError(null);
    try {
      const p = await api.parcelAt(pin[0], pin[1]);
      setParcel(p);
      setBoundary(p.boundary);
      if (!address.trim() && p.address) setAddress(p.address);
    } catch (e) {
      setParcelError((e as Error).message);
    } finally {
      setParcelBusy(false);
    }
  };

  const canContinue = !!boundary && name.trim().length > 0 && !saving;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!boundary) return;
    setSaving(true);
    setError(null);
    const apiSource: BoundarySource = source === "upload" ? "upload" : source === "parcel" ? "parcel" : "drawn";
    try {
      let id = projectId;
      if (!id) {
        const p = await api.createProject({ name: name.trim(), address: address.trim(), boundary });
        id = p.id;
        if (apiSource !== "drawn") await api.updateBoundary(id, boundary, apiSource);
      } else if (JSON.stringify(boundary) !== loadedBoundary.current) {
        await api.updateBoundary(id, boundary, apiSource);
      }
      router.push(`/projects/${id}/survey`);
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };

  return (
    <div className={styles.layout}>
      <form className={styles.left} onSubmit={submit} aria-busy={loading || saving}>
        <div className={styles.intro}>
          <p className="app-eyebrow">{projectId ? "Project" : "New project"} · Step 1 of 5</p>
          <h1 className="app-display">Start with the land.</h1>
          <p className="app-body">
            Name the property and set its boundary. Everything that follows, from contours to keylines, is measured
            inside this line.
          </p>
        </div>

        <div className={styles.fields}>
          <div className="field">
            <label className="field-label" htmlFor="name">Property name</label>
            <input
              id="name"
              className="input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Ridge Road farm"
              required
              autoComplete="off"
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="address">Address</label>
            <div className={styles.addressRow}>
              <input
                id="address"
                className="input"
                value={address}
                onChange={(e) => setAddress(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    findAddress();
                  }
                }}
                placeholder="700 Freestone Ranch Rd, Sebastopol"
                autoComplete="street-address"
                aria-describedby="address-help"
              />
              <button
                type="button"
                className="btn btn-sm"
                onClick={findAddress}
                disabled={searching || address.trim().length < 3}
              >
                {searching ? "Finding." : "Find"}
              </button>
            </div>
            <p id="address-help" className="app-small">
              Street address, or latitude, longitude. Search uses the US Census geocoder and county records.
            </p>
            {searchError && <p className="error-text" role="alert">{searchError}</p>}
            {candidates && candidates.length > 1 && (
              <ul className={styles.results} aria-label="Address matches">
                {candidates.map((c) => (
                  <li key={`${c.lng},${c.lat}`}>
                    <button
                      type="button"
                      className={`${styles.result} ${pin && pin[0] === c.lng && pin[1] === c.lat ? styles.resultOn : ""}`}
                      onClick={() => goTo([c.lng, c.lat])}
                    >
                      <span>{c.label}</span>
                      <span className="app-small">{c.source}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        <fieldset className={styles.sources}>
          <legend className="field-label">Boundary source</legend>

          <label className={`${styles.radioRow} ${source === "parcel" ? styles.checked : ""}`}>
            <input type="radio" name="source" value="parcel" checked={source === "parcel"} onChange={() => setSource("parcel")} />
            <span className={styles.radioText}>
              <span className="app-title">Import county parcel</span>
              <span className="app-small">The recorded parcel line at the address you found. Sonoma County for now.</span>
            </span>
          </label>
          {source === "parcel" && (
            <div className={styles.upload}>
              <button type="button" className="btn btn-sm" onClick={importParcel} disabled={!pin || parcelBusy}>
                {parcelBusy ? "Fetching parcel." : "Import parcel"}
              </button>
              <span className="app-small" aria-live="polite">
                {parcel
                  ? `APN ${parcel.apn ?? "—"}${parcel.acres ? ` · ${parcel.acres} recorded acres` : ""}`
                  : pin
                    ? "Uses the location you found."
                    : "Find the address first."}
              </span>
              {parcelError && <p className="error-text" role="alert">{parcelError}</p>}
            </div>
          )}

          <label className={`${styles.radioRow} ${source === "upload" ? styles.checked : ""}`}>
            <input
              type="radio"
              name="source"
              value="upload"
              checked={source === "upload"}
              onChange={() => setSource("upload")}
            />
            <span className={styles.radioText}>
              <span className="app-title">Upload a file</span>
              <span className="app-small">GeoJSON polygon in longitude and latitude.</span>
            </span>
          </label>
          {source === "upload" && (
            <div className={styles.upload}>
              <input
                ref={fileInput}
                id="boundary-file"
                type="file"
                accept=".geojson,.json,application/geo+json,application/json"
                className="sr-only"
                onChange={(e) => onFile(e.target.files?.[0])}
              />
              <label htmlFor="boundary-file" className="btn btn-sm">
                <IconUpload size={16} /> Choose GeoJSON
              </label>
              <span className="app-small" aria-live="polite">{fileName ?? "No file chosen."}</span>
              {fileError && <p className="error-text" role="alert">{fileError}</p>}
            </div>
          )}

          <label className={`${styles.radioRow} ${source === "drawn" ? styles.checked : ""}`}>
            <input
              type="radio"
              name="source"
              value="drawn"
              checked={source === "drawn"}
              onChange={() => setSource("drawn")}
            />
            <span className={styles.radioText}>
              <span className="app-title">Draw it on the map</span>
              <span className="app-small">Click each corner. Edit vertices after.</span>
            </span>
          </label>
        </fieldset>

        <dl className={styles.stats}>
          <div>
            <dt className="field-label">Area</dt>
            <dd>
              <span className="app-numeral">{formatAcres(area)}</span> <span className="app-small">acres</span>
            </dd>
          </div>
          <div>
            <dt className="field-label">Perimeter</dt>
            <dd>
              <span className="app-numeral">{formatMiles(perimeter)}</span> <span className="app-small">miles</span>
            </dd>
          </div>
        </dl>

        {error && <p className="error-text" role="alert">{error}</p>}

        <div className={styles.actions}>
          <button type="submit" className="btn btn-primary" disabled={!canContinue}>
            {saving ? "Saving." : "Continue to survey"} <IconArrowRight />
          </button>
          {!boundary && <span className="app-small">Set a boundary to continue.</span>}
          {boundary && !name.trim() && <span className="app-small">Name the property to continue.</span>}
        </div>
      </form>

      <div className={styles.mapPanel}>
        <BoundaryMap boundary={boundary} drawEnabled={source === "drawn"} onChange={setBoundary} flyTo={flyTo} />
      </div>
    </div>
  );
}
