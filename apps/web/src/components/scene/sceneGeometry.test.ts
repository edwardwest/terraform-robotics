import { test } from "node:test";
import assert from "node:assert/strict";
import { cameraPath, sizeAt, treesAt, TODAY, yearLabel } from "./sceneGeometry.ts";

test("growth matches the server's curve", () => {
  assert.equal(sizeAt(-1, 10, 8, 4), null);
  assert.ok(Math.abs(sizeAt(0, 10, 8, 4)![0] - 1.2) < 1e-9);
  assert.deepEqual(sizeAt(10, 10, 8, 4), [8, 4]);
  assert.deepEqual(sizeAt(0, 0, 18, 9), [18, 9]);
});

test("trees appear by year; today shows only existing ones", () => {
  const scene = {
    trees: [[-122, 38, 6, 4, 8, 2, 0], [-122.001, 38, 18, 9, 0, -100, 1]],
    tree_kinds: [{ type: "orchard", color: "#6f9a4a" }, { type: "windbreak", color: "#3d5e3a" }],
  } as never;
  const count = (y: number) => treesAt(scene, y).features.length;
  assert.equal(count(TODAY), 4); // existing windbreak: trunk + 3 tiers
  assert.equal(count(1), 4); // orchard not planted until year 2
  assert.equal(count(2), 7); // + trunk + 2 canopy tiers
  const tallest = Math.max(...treesAt(scene, 30).features.map((f) => f.properties.height));
  assert.ok(tallest >= 18 * 0.88 && tallest <= 18 * 1.12); // steady per-tree variation
});

test("camera glides through every view and takes the short way round", () => {
  const cam = (lon: number, bearing: number, d = 4) => ({ center: [lon, 38] as [number, number], zoom: 16, pitch: 60, bearing, duration_s: d });
  const path = cameraPath([cam(0, 350, 1), cam(1, 10), cam(2, 30)]);
  assert.equal(path.total, 8);
  assert.deepEqual(path.at(0).center, [0, 38]);
  assert.ok(Math.abs(path.at(4).center[0] - 1) < 1e-9 && Math.abs(path.at(4).bearing - 370) < 1e-9);
  assert.ok(Math.abs(path.at(8).center[0] - 2) < 1e-9);
  assert.ok(path.at(2).bearing > 350 && path.at(2).bearing < 370);
});

test("year label", () => {
  assert.equal(yearLabel(TODAY, [0, 2, 4]), "Today");
  assert.equal(yearLabel(3, [0, 2, 4]), "Year 3 · phase 2 built");
});
