/* The service worker: what makes the page installable and lets it receive
   the nightly push. It caches nothing — the pages are small, rebuilt daily,
   and the forecast is computed live, so a stale copy would be worse than a
   slow one. */
self.addEventListener("install", function () { self.skipWaiting(); });
self.addEventListener("activate", function (e) { e.waitUntil(self.clients.claim()); });

self.addEventListener("push", function (event) {
  var data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = { body: event.data && event.data.text() }; }
  event.waitUntil(self.registration.showNotification(data.title || "Beijing air", {
    body: data.body || "", icon: "/apple-touch-icon.png", badge: "/badge.png", tag: data.tag || "outlook",
    data: { url: data.url || "/beijing?topic=air" }, renotify: false,
  }));
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  var url = (event.notification.data && event.notification.data.url) || "/beijing?topic=air";
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (wins) {
    for (var i = 0; i < wins.length; i++) { var w = wins[i]; if ("navigate" in w) { return w.navigate(url).then(function () { return w.focus(); }); } }
    return self.clients.openWindow(url);
  }));
});
