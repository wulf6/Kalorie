const VERSION = 'v' + Date.now();
const CACHE = 'kalorie-' + VERSION;

// Při instalaci - smaž všechny staré cache
self.addEventListener('install', e => {
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// Network first - vždy stáhni novou verzi, cache jen jako fallback
self.addEventListener('fetch', e => {
  if(e.request.method !== 'GET') return;
  
  e.respondWith(
    fetch(e.request)
      .then(resp => {
        // Ulož do cache jen HTML a JS
        if(resp.ok && (e.request.url.includes('.html') || e.request.url.includes('.js'))){
          const clone = resp.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
        }
        return resp;
      })
      .catch(() => caches.match(e.request))
  );
});
