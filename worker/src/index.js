/**
 * weather-push — tomorrow's Beijing air, every night at 22:00.
 *
 * Runs on a cron. Fetches /api/forecast and /model/*.json from the site, runs
 * the very same model the page runs (templates/pm25model.js, bundled in), and
 * sends every subscribed device one notification with tomorrow's daily mean,
 * its verdict on the US scale, the clean and dirty hours, and the weather
 * behind it. Tapping opens the page on tomorrow's detail card.
 *
 * GET / returns what tonight's notification would say, without sending it.
 * GET /?send=<TRIGGER_KEY> sends it now, to every subscribed device.
 */
import PM25 from "../../templates/pm25model.js";
import { outlook, compose } from "../../templates/outlook.js";
import { sendPush } from "./webpush.js";

async function inputs(env) {
  const [fc, model, meta] = await Promise.all([
    fetch(env.SITE + "/api/forecast", { cf: { cacheTtl: 0 } }).then((r) => r.json()),
    fetch(env.SITE + "/model/pm25.json", { cf: { cacheTtl: 3600 } }).then((r) => r.json()),
    fetch(env.SITE + "/model/meta.json", { cf: { cacheTtl: 0 } }).then((r) => r.json()),
  ]);
  return { fc, model, meta };
}

async function build(env) {
  const { fc, model, meta } = await inputs(env);
  if (!fc.forecast) throw new Error("no forecast");
  const o = outlook(PM25, model, meta, fc);
  // The day after the last observed hour, in Beijing local time.
  const last = o.t[o.iNow] || o.t[0];
  const d = new Date(last.slice(0, 10) + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() + 1);
  const day = d.toISOString().slice(0, 10);
  return compose(o, meta, day);
}

async function sendAll(env, msg) {
  const v = { publicKey: env.VAPID_PUBLIC_KEY, privateKey: env.VAPID_PRIVATE_KEY, subject: env.VAPID_SUBJECT };
  let cursor, sent = 0, pruned = 0, failed = 0, total = 0;
  do {
    const page = await env.PUSH_SUBS.list({ prefix: "sub:", cursor });
    for (const k of page.keys) {
      total++;
      const rec = await env.PUSH_SUBS.get(k.name, "json");
      if (!rec) continue;
      try {
        const st = await sendPush(rec, msg, v);
        if (st === 404 || st === 410) { await env.PUSH_SUBS.delete(k.name); pruned++; }
        else if (st >= 200 && st < 300) sent++; else failed++;
      } catch { failed++; }
    }
    cursor = page.list_complete ? null : page.cursor;
  } while (cursor);
  return { total, sent, pruned, failed };
}

export default {
  async scheduled(event, env, ctx) {
    const msg = await build(env);
    const r = await sendAll(env, msg);
    console.log(JSON.stringify({ at: new Date().toISOString(), title: msg.title, ...r }));
  },
  async fetch(request, env) {
    const url = new URL(request.url);
    let msg;
    try { msg = await build(env); } catch (e) { return new Response(JSON.stringify({ error: String(e) }), { status: 500, headers: { "content-type": "application/json" } }); }
    const key = url.searchParams.get("send");
    if (key && env.TRIGGER_KEY && key === env.TRIGGER_KEY) {
      const r = await sendAll(env, msg);
      return new Response(JSON.stringify({ sent: true, ...r, message: msg }), { headers: { "content-type": "application/json" } });
    }
    return new Response(JSON.stringify({ sent: false, message: msg }, null, 1), { headers: { "content-type": "application/json" } });
  },
};
