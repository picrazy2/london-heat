/**
 * The quotsoft.net mirror of the CNEMC hourly publication, shared by /api/live
 * and /api/forecast. One CSV per day; rows are (date, hour, pollutant, station…).
 */
export const MIRROR = "https://quotsoft.net/air/data/beijing_all_";
export const CITIES = "https://quotsoft.net/air/data/china_cities_";
export const UA = { "User-Agent": "weather.akguo.com" };

// The city's designated clean-air control site and its regional background site
// measure something other than Beijing's air; the published city average omits
// them and so does this one.
const EXCLUDE = ["定陵", "京东南区域"];
export const excluded = (name) => EXCLUDE.some((x) => (name || "").includes(x));

export const num = (v) => {
  if (v === null || v === undefined) return null;
  const s = String(v).trim();
  if (!s || s === "NA" || s === "—" || s === "-") return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
};

export const mean = (xs) =>
  xs.length ? Math.round((xs.reduce((a, b) => a + b, 0) / xs.length) * 10) / 10 : null;

/** Beijing's calendar day `back` days ago, as YYYYMMDD and as a Date at 00:00 UTC. */
export function beijingDay(back) {
  const bj = new Date(Date.now() + 8 * 3600 * 1000);
  const d = new Date(bj.getTime() - back * 86400000);
  return { d, ymd: d.toISOString().slice(0, 10).replace(/-/g, "") };
}

/** One mirror day -> [{hour, values:{station: pm25}}], ascending. */
export function parseMirrorDay(text) {
  const lines = text.trim().split(/\r?\n/);
  if (lines.length < 2) return [];
  const cols = lines[0].split(",").slice(3);
  const keep = cols.map((c, i) => (excluded(c) ? -1 : i)).filter((i) => i >= 0);
  const out = [];
  for (let i = 1; i < lines.length; i++) {
    const p = lines[i].split(",");
    if (p.length < 4 || p[2] !== "PM2.5") continue;
    const hr = parseInt(p[1], 10);
    if (!Number.isInteger(hr) || hr < 0 || hr > 23) continue;
    const vals = p.slice(3), rec = {};
    for (const j of keep) {
      const v = num(vals[j]);
      if (v !== null && v >= 0 && v <= 1500) rec[cols[j]] = v;
    }
    if (Object.keys(rec).length >= 5) out.push({ hour: hr, values: rec });
  }
  out.sort((a, b) => a.hour - b.hour);
  return out;
}

/** The mirror's file for a day, parsed, or null. */
export async function fetchMirrorDay(ymd, ttl = 300) {
  const r = await fetch(MIRROR + ymd + ".csv", { headers: UA, cf: { cacheTtl: ttl, cacheEverything: true } });
  if (!r.ok) return null;
  return parseMirrorDay(await r.text());
}
