// MapLibre GL v6 loads its web worker from a URL next to the main bundle. Bundlers rewrite
// import.meta.url, so we serve a copy from /public and point setWorkerUrl() at it.
import { copyFileSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";

const require = createRequire(import.meta.url);
const pkgDir = dirname(require.resolve("maplibre-gl/package.json"));
const outDir = join(process.cwd(), "public", "vendor");
mkdirSync(outDir, { recursive: true });
copyFileSync(join(pkgDir, "dist", "maplibre-gl-worker.mjs"), join(outDir, "maplibre-gl-worker.mjs"));
console.log("maplibre: copied worker to public/vendor/maplibre-gl-worker.mjs");
