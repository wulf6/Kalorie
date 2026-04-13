const CACHE = "kalorie-v1";
const FILES = ["/Kalorie/", "/Kalorie/index.html", "/Kalorie/manifest.json"];

self.addEventListener("install", e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(FILES)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", e => {
  // Gemini API a Open Food Facts - vždy z internetu
  if (e.request.url.includes("googleapis") || e.request.url.includes("openfoodfacts")) {
    return;
  }
  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request).catch(() => caches.match("/Kalorie/index.html")))
  );
});
