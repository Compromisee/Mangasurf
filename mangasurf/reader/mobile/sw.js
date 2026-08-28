/* Mangasurf mobile service worker.
 *
 * Purpose: make the shell survive networks (Tailscale drop, Wi-Fi hop, the
 * host sleeping) so the app never bounces to a dead white screen. The app
 * shell — HTML, CSS, JS, icons — is cached on first load and served from
 * cache when the network is unavailable; API calls are always fetched live
 * (the token and payloads change per request, and caching POSTs would bite).
 *
 * The shell is cache-first for immutable assets and network-first for HTML so
 * a redeploy takes effect. Because the PWA is served by the host at a fixed
 * /pwa scope, the same worker works whether you reach it over your LAN IP or
 * a Tailscale 100.x address.
 */

const CACHE = 'mangasurf-mobile-v2';
const SHELL = ['./', './index.html', './style.css', './app.js'];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(SHELL).catch(() => {}))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);

  // Never try to cache API/stream requests: they need this request's token
  // and the bytes are reachable only while online.
  if (e.request.method !== 'GET') return;
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/stream/')) return;

  // Navigation: try network first so redeploys land, fall back to the shell.
  if (e.request.mode === 'navigate') {
    e.respondWith(
      fetch(e.request).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put('./index.html', copy)).catch(() => {});
        return res;
      }).catch(() => caches.match('./index.html'))
    );
    return;
  }

  // Everything else (CSS, JS, icons): cache-first, then network + cache the copy.
  e.respondWith(
    caches.match(e.request).then((hit) => hit || fetch(e.request).then((res) => {
      if (res.ok) {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
      }
      return res;
    }))
  );
});
