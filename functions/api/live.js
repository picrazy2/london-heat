/**
 * GET /api/live — what the instruments say right now.
 *
 * A Cloudflare Pages Function, so the static site gets one live endpoint without
 * a server. It exists rather than having the page call the sources directly for
 * three reasons: the Chinese monitoring feed sends no CORS header, so a browser
 * cannot read it; the response is cached at the edge, so a thousand readers are
 * one request upstream; and the shape the page consumes stays ours, so changing
 * a source later does not mean shipping new JavaScript.
 *
 * Beijing has two paths on purpose. The CNEMC real-time feed is the better one —
 * it carries station coordinates — but it is served on port 18007, and Workers
 * may only fetch on a fixed list of ports that does not include it. So the
 * mirror, which is ordinary HTTPS, is tried whenever the direct feed fails, and
 * returns the same readings without coordinates. The page keeps a station table
 * from build time and joins the two by name, so the map draws either way.
 *
 * Every source is optional. One that is down produces a null block, never a
 * failed response: the page already holds a baked snapshot and keeps showing it.
 */

const CNEMC =
  "https://air.cnemc.cn:18007/CityData/GetAQIDataPublishLive?cityName=%E5%8C%97%E4%BA%AC%E5%B8%82";
const MIRROR = "https://quotsoft.net/air/data/beijing_all_";

// The city's designated clean-air control site and its regional background site
// measure something other than Beijing's air; the published city average omits
// them and so does this one.
const EXCLUDE = ["定陵", "京东南区域"];
const excluded = (name) => EXCLUDE.some((x) => (name || "").includes(x));

const LONDON =
  "https://api.open-meteo.com/v1/forecast?latitude=51.4775&longitude=-0.4614" +
  "&current=temperature_2m,relative_humidity_2m,weather_code&timezone=Europe%2FLondon";

const TTL = 600; // seconds at the edge
const UA = { "User-Agent": "weather.akguo.com" };

const num = (v) => {
  if (v === null || v === undefined) return null;
  const s = String(v).trim();
  if (!s || s === "NA" || s === "—" || s === "-") return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
};

const mean = (xs) =>
  xs.length ? Math.round((xs.reduce((a, b) => a + b, 0) / xs.length) * 10) / 10 : null;

function beijingTime(d) {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Shanghai", day: "numeric", month: "short",
    hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(d);
}

/** Preferred: the monitoring centre's own feed, with coordinates. */
async function beijingDirect() {
  const r = await fetch(CNEMC, {
    headers: { ...UA, accept: "application/json" },
    cf: { cacheTtl: TTL, cacheEverything: true },
  });
  if (!r.ok) return null;
  const rows = await r.json();
  if (!Array.isArray(rows) || !rows.length) return null;

  const stations = [];
  for (const s of rows) {
    const lat = num(s.Latitude), lon = num(s.Longitude);
    if (lat === null || lon === null || excluded(s.PositionName)) continue;
    stations.push({
      code: s.StationCode, name: s.PositionName, lat, lon,
      pm25: num(s.PM2_5), pm25_24h: num(s.PM2_5_24h), pm10: num(s.PM10),
      o3: num(s.O3_8h), no2: num(s.NO2), so2: num(s.SO2), co: num(s.CO),
      aqi_cn: num(s.AQI),
    });
  }
  if (!stations.length) return null;
  const t = rows[0].TimePoint ? new Date(rows[0].TimePoint + "+08:00") : null;
  return {
    source: "cnemc",
    city: mean(stations.map((s) => s.pm25_24h).filter((v) => v !== null)),
    hour: mean(stations.map((s) => s.pm25).filter((v) => v !== null)),
    n: stations.filter((s) => s.pm25_24h !== null).length,
    time: t && !Number.isNaN(+t) ? beijingTime(t) : null,
    stations,
  };
}

/** One mirror day -> [{hour, values:{station: pm25}}], ascending. */
function parseMirrorDay(text) {
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

/**
 * Fallback: the hourly mirror, which carries readings but no coordinates.
 *
 * The mirror publishes a PM2.5_24h column and leaves it empty — always, on every
 * day checked. So the 24-hour mean is computed here from the hourly series
 * across yesterday and today rather than read off a field that does not exist.
 * That matters: both AQI scales are defined on the 24-hour mean, and quietly
 * substituting the current hour would make the headline index jump around with
 * every passing car.
 */
async function beijingMirror() {
  const bj = new Date(Date.now() + 8 * 3600 * 1000);   // Beijing's calendar day
  const days = [];
  for (let back = 1; back >= 0; back--) {
    const d = new Date(bj.getTime() - back * 86400000);
    const ymd = d.toISOString().slice(0, 10).replace(/-/g, "");
    try {
      const r = await fetch(MIRROR + ymd + ".csv", {
        headers: UA, cf: { cacheTtl: 300, cacheEverything: true },
      });
      if (!r.ok) continue;
      days.push({ d, rows: parseMirrorDay(await r.text()) });
    } catch { /* a missing day is survivable; one day still gives a mean */ }
  }
  const flat = [];
  for (const day of days) for (const r of day.rows) flat.push({ d: day.d, ...r });
  if (!flat.length) return null;

  const window24 = flat.slice(-24);
  const latest = flat[flat.length - 1];

  const sums = {}, counts = {};
  for (const row of window24) {
    for (const name in row.values) {
      sums[name] = (sums[name] || 0) + row.values[name];
      counts[name] = (counts[name] || 0) + 1;
    }
  }
  const names = [...new Set([...Object.keys(sums), ...Object.keys(latest.values)])];
  const stations = names.map((n) => ({
    name: n, lat: null, lon: null,
    pm25: latest.values[n] ?? null,
    // The same completeness rule the archive uses: a mean over eight hours is
    // not a 24-hour mean, and should not be labelled as one.
    pm25_24h: counts[n] >= 18 ? Math.round((sums[n] / counts[n]) * 10) / 10 : null,
  }));

  const v24 = stations.map((s) => s.pm25_24h).filter((v) => v !== null);
  const MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return {
    source: "mirror",
    city: v24.length ? mean(v24) : mean(Object.values(latest.values)),
    hour: mean(Object.values(latest.values)),
    n: v24.length || Object.keys(latest.values).length,
    time: `${latest.d.getUTCDate()} ${MON[latest.d.getUTCMonth()]}, ` +
          `${String(latest.hour).padStart(2, "0")}:00`,
    stations,
  };
}

async function beijing() {
  const direct = await beijingDirect().catch(() => null);
  if (direct) return direct;
  return beijingMirror().catch(() => null);
}

async function london() {
  const r = await fetch(LONDON, { headers: UA, cf: { cacheTtl: TTL, cacheEverything: true } });
  if (!r.ok) return null;
  const j = await r.json();
  if (!j || !j.current) return null;
  return {
    temp: j.current.temperature_2m ?? null,
    humidity: j.current.relative_humidity_2m ?? null,
    time: j.current.time ?? null,
  };
}

export async function onRequestGet({ request }) {
  const cache = caches.default;
  const key = new Request(new URL(request.url).origin + "/api/live", request);
  const hit = await cache.match(key);
  if (hit) return hit;

  const [bj, ldn] = await Promise.all([beijing(), london().catch(() => null)]);
  const body = JSON.stringify({ beijing: bj, london: ldn, fetched: new Date().toISOString() });

  const res = new Response(body, {
    headers: {
      "content-type": "application/json; charset=utf-8",
      // A short browser cache and a longer edge one, with stale-while-revalidate
      // so a slow upstream never makes a reader wait for a number that only
      // changes once an hour anyway.
      "cache-control": `public, max-age=120, s-maxage=${TTL}, stale-while-revalidate=1800`,
      "access-control-allow-origin": "*",
    },
  });
  // Never cache a response in which everything failed — that would pin the
  // outage in place for the full TTL.
  if (bj || ldn) await cache.put(key, res.clone());
  return res;
}
