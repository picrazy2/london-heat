/* ── The nightly outlook, on this device ───────────────────────────────────
   A bell in the forecast card. On: this browser is subscribed to Web Push
   and the worker sends tomorrow's air at 22:00 Beijing time. The subscription
   is stored by /api/push; nothing else about the device is. Hidden where the
   browser cannot do push (Safari on iOS needs the page added to the Home
   Screen first). */
(function () {
  "use strict";
  var VAPID_PUBLIC = "BJEEBcgoGsqwByDlu46m0dK89GoxOS9b-1QWj6QO9OOgjWZ2rLx99NGgakudNtAM8VenI3d9v6h9g1TfwJuA2OY";
  var bell = document.getElementById("fcBell");
  if (!bell || !("serviceWorker" in navigator)) return;
  document.documentElement.classList.add("dash");
  var reg = navigator.serviceWorker.register("/sw.js").catch(function () { return null; });
  var supported = "PushManager" in window && "Notification" in window;
  if (!supported) return;

  function b64(s) { var pad = "=".repeat((4 - (s.length % 4)) % 4); var raw = atob((s + pad).replace(/-/g, "+").replace(/_/g, "/")); var a = new Uint8Array(raw.length); for (var i = 0; i < raw.length; i++) a[i] = raw.charCodeAt(i); return a; }
  function set(on) { bell.setAttribute("aria-pressed", String(on)); bell.title = on ? "Nightly outlook on · tap to turn off" : "Get tomorrow's air at 10 pm"; }
  function toast(msg) { var t = document.getElementById("tip"); if (!t) return; t.innerHTML = msg; t.style.opacity = 1; t.style.left = "50%"; t.style.top = (bell.getBoundingClientRect().top - 6) + "px"; setTimeout(function () { t.style.opacity = 0; }, 2600); }

  reg.then(function (r) {
    if (!r) return;
    bell.hidden = false;
    if (Notification.permission === "denied") { bell.title = "Notifications are blocked for this site in your browser settings"; bell.disabled = true; return; }
    return r.pushManager.getSubscription().then(function (s) { set(!!s); });
  });

  bell.addEventListener("click", function () {
    bell.disabled = true;
    reg.then(function (r) {
      if (!r) throw new Error("no service worker");
      return r.pushManager.getSubscription().then(function (s) {
        if (s) {
          return fetch("/api/push", { method: "DELETE", headers: { "content-type": "application/json" }, body: JSON.stringify({ endpoint: s.endpoint }) })
            .then(function () { return s.unsubscribe(); }).then(function () { set(false); toast("Nightly outlook off"); });
        }
        return Notification.requestPermission().then(function (p) {
          if (p !== "granted") throw new Error("Notifications weren't allowed");
          return r.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64(VAPID_PUBLIC) });
        }).then(function (sub) {
          return fetch("/api/push", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ subscription: sub.toJSON(), tz: Intl.DateTimeFormat().resolvedOptions().timeZone }) })
            .then(function (res) { if (!res.ok) throw new Error("couldn't save the subscription"); set(true); toast("Tomorrow's air, every night at 10 pm"); });
        });
      });
    }).catch(function (e) { toast(e && e.message ? e.message : "Couldn't change notifications"); }).then(function () { bell.disabled = false; });
  });
})();
