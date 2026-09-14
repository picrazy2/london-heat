/**
 * GET /api/forecast — everything the PM2.5 forecast model needs, in one call.
 *
 * The model itself runs in the browser (templates/pm25model.js, with the trees
 * in /model/pm25.json). This endpoint only gathers its inputs, because two of
 * the three sources send no CORS header and none should be hit by every reader:
 *
 *   forecast  Open-Meteo, hourly, seven days back (the history features need
 *             72 h of run-up and the chart shows the past week) and seven ahead,
 *             with the 925/850/700 hPa levels the sounding features are made from.
 *   obs       The last week of Beijing's hourly city mean from the CNEMC
 *             mirror, keyed by local hour. The residual model starts from the
 *             last observed hour; the chart draws the model over the past days.
 *   upwind    The surrounding cities' PM2.5 and PM10 at the latest published
 *             hour, grouped by the direction they lie in from Beijing. Only the
 *             two pollutant rows for that hour are parsed out of a 440 KB file.
 *
 * Every block is optional and null when its source is down; the page degrades
 * to whatever it has (no upwind -> the residual model sees missing values,
 * which it was trained with; no obs -> weather-only; no forecast -> nothing).
 */
import { CITIES, UA, mean, num, beijingDay, fetchMirrorDay } from "../_lib/mirror.js";

const TTL = 600;
const LAT = 39.9042, LON = 116.4074;
const SURF = ["temperature_2m", "relative_humidity_2m", "dew_point_2m", "precipitation", "rain", "snowfall",
  "pressure_msl", "surface_pressure", "cloud_cover", "cloud_cover_low", "wind_speed_10m", "wind_direction_10m",
  "wind_gusts_10m", "wind_speed_100m", "wind_direction_100m", "boundary_layer_height", "shortwave_radiation",
  "vapour_pressure_deficit"];
const LEV = [925, 850, 700].flatMap((p) => ["temperature", "wind_speed", "wind_direction"].map((v) => `${v}_${p}hPa`));
const OPEN_METEO =
  `https://api.open-meteo.com/v1/forecast?latitude=${LAT}&longitude=${LON}&hourly=${[...SURF, ...LEV].join(",")}` +
  "&timezone=Asia%2FShanghai&wind_speed_unit=ms&past_days=7&forecast_days=7&models=best_match";

// The same grouping as ml/dataset.py CITY_GROUPS. South is the Hebei plain the
// south wind blows in from; north-west is the steppe the dust comes from.
const GROUPS = {
  south: ["保定", "石家庄", "廊坊", "沧州", "衡水", "邢台", "邯郸"],
  east: ["天津", "唐山", "秦皇岛"],
  northwest: ["张家口", "呼和浩特", "乌兰察布", "包头", "锡林郭勒盟"],
  north: ["承德"], southwest: ["太原"],
};

async function forecast() {
  const r = await fetch(OPEN_METEO, { headers: UA, cf: { cacheTtl: TTL, cacheEverything: true } });
  if (!r.ok) return null;
  const j = await r.json();
  if (!j || !j.hourly || !Array.isArray(j.hourly.time)) return null;
  return j.hourly;
}

/** {"2026-09-14T11:00": 3.1, …} for the last week of Beijing days. */
async function observations() {
  const out = {};
  for (let back = 6; back >= 0; back--) {
    const { d, ymd } = beijingDay(back);
    let rows = null;
    try { rows = await fetchMirrorDay(ymd); } catch { /* a missing day is survivable */ }
    if (!rows) continue;
    const day = d.toISOString().slice(0, 10);
    for (const row of rows) {
      const v = mean(Object.values(row.values));
      if (v !== null) out[`${day}T${String(row.hour).padStart(2, "0")}:00`] = v;
    }
  }
  return Object.keys(out).length ? out : null;
}

/** Group means of PM2.5 and PM10 at the latest hour the cities file carries. */
async function upwind() {
  for (let back = 0; back <= 1; back++) {
    const { d, ymd } = beijingDay(back);
    let text;
    try {
      const r = await fetch(CITIES + ymd + ".csv", { headers: UA, cf: { cacheTtl: 300, cacheEverything: true } });
      if (!r.ok) continue;
      text = await r.text();
    } catch { continue; }
    const lines = text.split(/\r?\n/);
    if (lines.length < 2) continue;
    const cols = lines[0].split(",");
    const idx = {};
    cols.forEach((c, i) => { idx[c] = i; });
    // Walk from the bottom: the latest hour with a PM2.5 row is the one wanted.
    let best = null;
    for (let i = lines.length - 1; i >= 1 && !best; i--) {
      const p = lines[i].split(",");
      if (p[2] !== "PM2.5") continue;
      const hr = parseInt(p[1], 10);
      const pm10 = lines.slice(Math.max(1, i - 40), i + 40).map((l) => l.split(","))
        .find((q) => q[2] === "PM10" && q[1] === p[1]);
      const rec = {};
      for (const [g, cities] of Object.entries(GROUPS)) {
        const v25 = cities.map((c) => idx[c] !== undefined ? num(p[idx[c]]) : null).filter((v) => v !== null);
        rec[`c_${g}_PM25`] = mean(v25);
        if (pm10) {
          const v10 = cities.map((c) => idx[c] !== undefined ? num(pm10[idx[c]]) : null).filter((v) => v !== null);
          rec[`c_${g}_PM10`] = mean(v10);
        }
      }
      if (rec.c_south_PM25 !== null) {
        best = { time: `${d.toISOString().slice(0, 10)}T${String(hr).padStart(2, "0")}:00`, ...rec };
      }
    }
    if (best) return best;
  }
  return null;
}

export async function onRequestGet({ request }) {
  const cache = caches.default;
  const key = new Request(new URL(request.url).origin + "/api/forecast", request);
  const hit = await cache.match(key);
  if (hit) return hit;

  const [fc, obs, up] = await Promise.all([
    forecast().catch(() => null), observations().catch(() => null), upwind().catch(() => null),
  ]);
  const body = JSON.stringify({ forecast: fc, obs, upwind: up, fetched: new Date().toISOString() });
  const res = new Response(body, {
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": `public, max-age=120, s-maxage=${TTL}, stale-while-revalidate=1800`,
      "access-control-allow-origin": "*",
    },
  });
  if (fc) await cache.put(key, res.clone());
  return res;
}
