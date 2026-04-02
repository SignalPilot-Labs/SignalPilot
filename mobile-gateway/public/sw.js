/**
 * SignalPilot PWA Service Worker
 * Caches static assets for offline shell, proxied content always goes to network.
 */
const CACHE_NAME = 'sp-mobile-v1';
const SHELL_ASSETS = [
  '/',
  '/login',
  '/public/icon-192.svg',
  '/public/icon-512.svg',
  '/manifest.json',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Never cache API calls or proxied app/monitor content
  if (
    url.pathname.startsWith('/api/') ||
    url.pathname.startsWith('/app') ||
    url.pathname.startsWith('/monitor') ||
    url.pathname.startsWith('/gateway-api') ||
    url.pathname.startsWith('/monitor-api')
  ) {
    return; // Let the browser handle these normally (network only)
  }

  // For shell assets: network-first, fallback to cache
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
