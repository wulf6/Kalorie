const CACHE = "kalorie-v4";
const FILES = [
  "/Kalorie/",
  "/Kalorie/index.html",
  "/Kalorie/db.json",
  "/Kalorie/manifest.json",
  "/Kalorie/icon.svg"
];

self.addEventListener("install", e => {
  e.waitUntil(
    caches.open(CACHE)
      .then(c => c.addAll(FILES))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", e => {
  // API volání vždy přes internet
  if (e.request.url.includes("googleapis") ||
      e.request.url.includes("openfoodfacts") ||
      e.request.url.includes("workers.dev") ||
      e.request.url.includes("jsdelivr")) {
    return;
  }
  // Vše ostatní z cache, pak network
  e.respondWith(
    caches.match(e.request)
      .then(cached => cached || fetch(e.request)
        .then(resp => {
          // Cachuj nové soubory
          if(resp.ok){
            const clone = resp.clone();
            caches.open(CACHE).then(c => c.put(e.request, clone));
          }
          return resp;
        })
        .catch(() => caches.match("/Kalorie/index.html"))
      )
  );
});
