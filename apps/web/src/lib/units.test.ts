// Run with: npm test  (Node's built-in test runner; Node >= 22.18 strips TS types natively)
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  mToFt, ftToM, m2ToAcres, acresToM2, mToMiles, m2ToFt2, ft2ToM2, m3ToGal, galToM3, mmToIn, inToMm,
  formatAcres, formatFeet, formatMiles, formatPct, formatResolution, niceStep, ticks,
} from "./units.ts";

const close = (a: number, b: number, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, `${a} != ${b}`);

test("length conversions", () => {
  close(mToFt(1), 3.280839895);
  close(mToFt(0.3048), 1);
  close(ftToM(mToFt(123.4)), 123.4);
  close(mToMiles(1609.344), 1);
});

test("area conversions", () => {
  close(m2ToAcres(4046.8564224), 1);
  close(acresToM2(40), 161874.256896);
  close(m2ToAcres(acresToM2(7.25)), 7.25);
});

test("formatters", () => {
  assert.equal(formatAcres(162000.5), "40.0");
  assert.equal(formatAcres(4046.8564224 * 2.5), "2.50");
  assert.equal(formatMiles(1640.2), "1.02");
  assert.equal(formatFeet(118.7), "389");
  assert.equal(formatFeet(null), "—");
  assert.equal(formatPct(82), "82%");
  assert.equal(formatResolution(0.5), "1.6 ft");
  assert.equal(formatResolution(10), "33 ft");
});

test("axis ticks", () => {
  assert.equal(niceStep(100, 5), 20);
  assert.equal(niceStep(7, 5), 1);
  assert.deepEqual(ticks(0, 100, 5), [0, 20, 40, 60, 80, 100]);
  assert.deepEqual(ticks(138, 389, 5), [150, 200, 250, 300, 350]);
});

test("area, volume and rainfall conversions", () => {
  close(m2ToFt2(1), 10.7639104, 1e-6);
  close(ft2ToM2(m2ToFt2(42)), 42);
  close(m3ToGal(1), 264.172052);
  close(galToM3(5000), 18.92705892, 1e-6);
  close(mmToIn(25.4), 1);
  close(inToMm(30), 762);
});
