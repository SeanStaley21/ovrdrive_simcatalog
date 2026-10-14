var VERSION = '20261013c';
var CACHE_PREFIX = 'simcatalog-';
var SHELL = CACHE_PREFIX + 'shell-' + VERSION;
var IMG = CACHE_PREFIX + 'img-' + VERSION;
var PRECACHE = [
  './',
  'css/main.css',
  'css/mobile.css',
  'css/popups.css',
  'css/records.css',
  'rigRecords/records.js',
  'data/cars.json',
  'data/tracks.json',
  'db/userSetRecords.json',
  'favicon.png',
  'manifest.webmanifest',
  'icons/icon-192.png',
  'icons/icon-512.png',
  'logos/logo with text.png'
];
var IMAGE_DIRS = /\/(cars|tracks|logos|icons|thumbs)\//;

self.addEventListener('install', function (e) {
  e.waitUntil(
    caches.open(SHELL).then(function (cache) {
      return cache.addAll(PRECACHE.map(function (u) {
        return new Request(u, { cache: 'reload' });
      }));
    }).then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.filter(function (k) {
        return k.indexOf(CACHE_PREFIX) === 0 && k !== SHELL && k !== IMG;
      }).map(function (k) { return caches.delete(k); }));
    }).then(function () { return self.clients.claim(); })
  );
});

// Looks in every cache (ignoring the query string) before the network; a
// response that passes accept() is stored under key in cacheName, and the
// event stays alive until the write finishes.
function cacheFirst(e, req, key, cacheName, accept) {
  return caches.match(key, { ignoreSearch: true }).then(function (hit) {
    if (hit) return hit;
    return fetch(req).then(function (res) {
      if (accept(res)) {
        var copy = res.clone();
        e.waitUntil(caches.open(cacheName).then(function (c) { return c.put(key, copy); }));
      }
      return res;
    });
  });
}

// Fetches past the HTTP cache so edits to the file show up on the next load;
// a good response replaces the cached copy, which is the offline fallback.
function networkFirst(e, req, key) {
  return fetch(req, { cache: 'no-cache' }).then(function (res) {
    if (isOk(res)) {
      var copy = res.clone();
      e.waitUntil(caches.open(SHELL).then(function (c) { return c.put(key, copy); }));
    }
    return res;
  }).catch(function () {
    return caches.match(key, { ignoreSearch: true }).then(function (hit) {
      return hit || Response.error();
    });
  });
}

function isOk(res) { return res.status === 200; }
function isOkOrOpaque(res) { return res.ok || res.type === 'opaque'; }

self.addEventListener('fetch', function (e) {
  var req = e.request;
  if (req.method !== 'GET') return;
  var url = new URL(req.url);

  if (url.hostname === 'fonts.googleapis.com' || url.hostname === 'fonts.gstatic.com') {
    e.respondWith(cacheFirst(e, req, req, SHELL, isOkOrOpaque));
    return;
  }
  if (url.origin !== self.location.origin) return;

  var key = url.origin + url.pathname;
  if (req.mode === 'navigate' && /(\/|index\.html)$/.test(url.pathname)) {
    e.respondWith(cacheFirst(e, req, './', SHELL, isOk));
  } else if (req.destination === 'image' || IMAGE_DIRS.test(url.pathname)) {
    e.respondWith(cacheFirst(e, req, key, IMG, isOk));
  } else if (/\/db\/userSetRecords\.json$/.test(url.pathname)) {
    e.respondWith(networkFirst(e, req, key));
  } else {
    e.respondWith(cacheFirst(e, req, key, SHELL, isOk));
  }
});
