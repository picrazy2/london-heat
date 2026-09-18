/**
 * /api/push — this device's Web Push subscription.
 *
 *   POST   {subscription}   store it (keyed by a hash of its endpoint)
 *   DELETE {endpoint}       forget it
 *
 * Subscriptions live in the PUSH_SUBS KV namespace, which the nightly worker
 * (worker/) reads when it sends the 22:00 outlook. There is no account: a
 * subscription is a browser's opaque endpoint plus its keys, and holding it
 * is the whole of what "notifications on" means for a device.
 */
const JSONH = { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" };

async function keyFor(endpoint) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(endpoint));
  return "sub:" + [...new Uint8Array(buf)].slice(0, 16).map((b) => b.toString(16).padStart(2, "0")).join("");
}

export async function onRequestPost({ request, env }) {
  if (!env.PUSH_SUBS) return new Response(JSON.stringify({ ok: false, error: "no store bound" }), { status: 500, headers: JSONH });
  let body;
  try { body = await request.json(); } catch { return new Response(JSON.stringify({ ok: false, error: "bad json" }), { status: 400, headers: JSONH }); }
  const s = body && body.subscription;
  if (!s || typeof s.endpoint !== "string" || !s.keys || !s.keys.p256dh || !s.keys.auth || !/^https:\/\//.test(s.endpoint)) {
    return new Response(JSON.stringify({ ok: false, error: "not a push subscription" }), { status: 400, headers: JSONH });
  }
  const rec = { endpoint: s.endpoint, p256dh: s.keys.p256dh, auth: s.keys.auth, ua: (request.headers.get("user-agent") || "").slice(0, 200),
                tz: body.tz || null, added: new Date().toISOString() };
  await env.PUSH_SUBS.put(await keyFor(s.endpoint), JSON.stringify(rec));
  return new Response(JSON.stringify({ ok: true }), { headers: JSONH });
}

export async function onRequestDelete({ request, env }) {
  if (!env.PUSH_SUBS) return new Response(JSON.stringify({ ok: false }), { status: 500, headers: JSONH });
  let body;
  try { body = await request.json(); } catch { body = {}; }
  if (body && typeof body.endpoint === "string") await env.PUSH_SUBS.delete(await keyFor(body.endpoint));
  return new Response(JSON.stringify({ ok: true }), { headers: JSONH });
}
