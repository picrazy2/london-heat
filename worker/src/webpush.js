/* Dependency-free Web Push: RFC 8291 (aes128gcm) payload encryption and
   RFC 8292 (VAPID) authorisation on Web Crypto, so it runs in a Worker with no
   packages. The same code the budget app's edge function uses. */
function concat(...arrs) { const out = new Uint8Array(arrs.reduce((s, a) => s + a.length, 0)); let o = 0; for (const a of arrs) { out.set(a, o); o += a.length; } return out; }
export function b64urlToBytes(s) { const pad = "=".repeat((4 - (s.length % 4)) % 4); const raw = atob((s + pad).replace(/-/g, "+").replace(/_/g, "/")); const arr = new Uint8Array(raw.length); for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i); return arr; }
function bytesToB64url(b) { let s = ""; for (let i = 0; i < b.length; i++) s += String.fromCharCode(b[i]); return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""); }
async function hkdf(salt, ikm, info, len) { const key = await crypto.subtle.importKey("raw", ikm, "HKDF", false, ["deriveBits"]); return new Uint8Array(await crypto.subtle.deriveBits({ name: "HKDF", hash: "SHA-256", salt, info }, key, len * 8)); }

async function importVapidSigningKey(v) {
  const d = b64urlToBytes(v.privateKey), pub = b64urlToBytes(v.publicKey);
  const jwk = { kty: "EC", crv: "P-256", d: bytesToB64url(d), x: bytesToB64url(pub.slice(1, 33)), y: bytesToB64url(pub.slice(33, 65)), ext: true };
  return crypto.subtle.importKey("jwk", jwk, { name: "ECDSA", namedCurve: "P-256" }, false, ["sign"]);
}
async function vapidAuthHeader(endpoint, v, signingKey) {
  const u = new URL(endpoint); const enc = (o) => bytesToB64url(new TextEncoder().encode(JSON.stringify(o)));
  const input = `${enc({ typ: "JWT", alg: "ES256" })}.${enc({ aud: `${u.protocol}//${u.host}`, exp: Math.floor(Date.now() / 1000) + 12 * 3600, sub: v.subject })}`;
  const sig = new Uint8Array(await crypto.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, signingKey, new TextEncoder().encode(input)));
  return `vapid t=${input}.${bytesToB64url(sig)}, k=${v.publicKey}`;
}
async function encryptPayload(payload, sub) {
  const uaPublic = b64urlToBytes(sub.p256dh), authSecret = b64urlToBytes(sub.auth);
  const as = await crypto.subtle.generateKey({ name: "ECDH", namedCurve: "P-256" }, true, ["deriveBits"]);
  const asPublic = new Uint8Array(await crypto.subtle.exportKey("raw", as.publicKey));
  const uaKey = await crypto.subtle.importKey("raw", uaPublic, { name: "ECDH", namedCurve: "P-256" }, false, []);
  const ecdh = new Uint8Array(await crypto.subtle.deriveBits({ name: "ECDH", public: uaKey }, as.privateKey, 256));
  const te = new TextEncoder();
  const ikm = await hkdf(authSecret, ecdh, concat(te.encode("WebPush: info\0"), uaPublic, asPublic), 32);
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const cek = await hkdf(salt, ikm, te.encode("Content-Encoding: aes128gcm\0"), 16);
  const nonce = await hkdf(salt, ikm, te.encode("Content-Encoding: nonce\0"), 12);
  const cekKey = await crypto.subtle.importKey("raw", cek, "AES-GCM", false, ["encrypt"]);
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv: nonce, tagLength: 128 }, cekKey, concat(payload, new Uint8Array([0x02]))));
  return concat(salt, new Uint8Array([0, 0, 0x10, 0x00]), new Uint8Array([65]), asPublic, ct);
}
/** Send one push. Returns the HTTP status (201 ok; 404/410 = subscription gone). */
export async function sendPush(sub, message, v) {
  const signingKey = await importVapidSigningKey(v);
  const [auth, body] = await Promise.all([vapidAuthHeader(sub.endpoint, v, signingKey), encryptPayload(new TextEncoder().encode(JSON.stringify(message)), sub)]);
  const res = await fetch(sub.endpoint, { method: "POST", headers: { TTL: "43200", Urgency: "normal", "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream", Authorization: auth }, body });
  return res.status;
}
