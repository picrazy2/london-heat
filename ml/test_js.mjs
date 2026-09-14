// node ml/test_js.mjs — the JS feature port against the Python test vector.
import { createRequire } from "node:module"; import fs from "node:fs";
const require = createRequire(import.meta.url);
const PM25 = require("../templates/pm25model.js");
const v = JSON.parse(fs.readFileSync(new URL("./out/js_test_vector.json", import.meta.url)));
const model = JSON.parse(fs.readFileSync(new URL("../data/pm25_model.json", import.meta.url)));
const raw = { ...v.raw, time: v.raw.time.map(s => s.replace(" ", "T")) };
const t0 = Date.now();
const { X } = PM25.features(raw, v.cols, v.level365, model.cny);
let bad = 0;
v.cols.forEach((c, j) => {
  const py = v.features[c]; let worst = 0, wi = -1;
  for (let i = 0; i < py.length; i++) {
    const a = py[i] == null ? NaN : py[i], b = X[i][j];
    const d = Number.isNaN(a) && Number.isNaN(b) ? 0 : Math.abs(a - b);
    if (!(d <= 1e-9)) { if (!(d <= worst)) { worst = d; wi = i; } }
  }
  if (wi >= 0) { bad++; console.log(`MISMATCH ${c}: worst at ${wi} py=${py[wi]} js=${X[wi][j]}`); }
});
const w = PM25.predict(model.w.trees, X);
let wd = 0; for (let i = 0; i < w.length; i++) wd = Math.max(wd, Math.abs(w[i] - v.w[i]));
console.log(`${v.cols.length} columns, ${bad} mismatched; W prediction max |diff| ${wd.toExponential(2)}; ${Date.now() - t0} ms`);
process.exit(bad || wd > 1e-6 ? 1 : 0);
