/* Service worker di LifeTracker.
   Strategia:
   - risorse statiche (/static/...): cache-first (cambiano solo con un nuovo deploy → CACHE_VERSION);
   - pagine HTML: sempre dalla rete (dati personali sempre aggiornati); se offline → pagina /offline.
   Nessun dato personale viene salvato in cache. */
const CACHE_VERSION = "lt-v2";
const PRECACHE = [
  "/offline",
  "/static/css/app.css",
  "/static/js/app.js",
  "/static/js/theme.js",
  "/static/vendor/bootstrap/bootstrap.min.css",
  "/static/vendor/bootstrap/bootstrap.bundle.min.js",
  "/static/vendor/bootstrap-icons/bootstrap-icons.min.css",
  "/static/img/icon-192.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_VERSION).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.match(request).then((cached) => cached || fetch(request).then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE_VERSION).then((cache) => cache.put(request, copy));
        }
        return response;
      }))
    );
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.match("/offline")));
  }
});
