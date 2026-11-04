/* TickLens service worker: lets the app be installed and open its shell offline.
   App code is network-first (updates show on the next load; the cache is only a fallback).
   Market data is never cached: /api/* and the /ws socket always go to the server. */
const CACHE = "ticklens-shell-v1";
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil((async () => {
  for (const k of await caches.keys()) if (k !== CACHE) await caches.delete(k);
  await self.clients.claim();
})()));
self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin) return;
  if (!(u.pathname === "/" || u.pathname.startsWith("/static/") || u.pathname === "/manifest.webmanifest")) return;   // /api, /ws: straight to the network
  e.respondWith((async () => {
    try {
      const r = await fetch(e.request, { cache: "no-cache" });
      if (r.ok) { const c = await caches.open(CACHE); c.put(e.request, r.clone()); }
      return r;
    } catch (err) {
      const hit = await caches.match(e.request);
      if (hit) return hit;
      throw err;
    }
  })());
});
