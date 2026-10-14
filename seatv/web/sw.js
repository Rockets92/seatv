// Service worker della guida installata come app: tiene in cache la pagina,
// i loghi e l'ultima guida letta, così l'app si apre anche senza rete.
// La versione cambia a ogni aggiornamento del sito e fa ripartire la cache.
"use strict";

const VERSION = "__BUILD__";
const SHELL = `seatv-shell-${VERSION}`;
const DATA = "seatv-data";
const LOGOS = "seatv-logos";
const SHELL_FILES = [
  "./",
  "manifest.webmanifest",
  "static/guide.css",
  "static/guide.js",
  "static/logo.png",
  "static/icon-192.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL).then((cache) => cache.addAll(SHELL_FILES)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("seatv-shell-") && k !== SHELL).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// Prima la rete, poi la copia salvata: per la pagina e i dati della guida.
async function networkFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
  try {
    const response = await fetch(request);
    if (response.ok) cache.put(request, response.clone());
    return response;
  } catch (err) {
    const cached = await cache.match(request, { ignoreSearch: true });
    if (cached) return cached;
    throw err;
  }
}

// Prima la copia salvata: per loghi e file statici, che cambiano di rado.
async function cacheFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) cache.put(request, response.clone());
  return response;
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  const scope = new URL(self.registration.scope);
  // Solo i file del sito; i feed XMLTV (grandi) e le immagini esterne passano diretti.
  if (url.origin !== scope.origin || !url.pathname.startsWith(scope.pathname)) return;
  const path = url.pathname.slice(scope.pathname.length);
  if (/\.xml(\.gz)?$/.test(path)) return;

  if (path.startsWith("logos/")) event.respondWith(cacheFirst(request, LOGOS));
  else if (path.startsWith("api/") || request.mode === "navigate") event.respondWith(networkFirst(request, path.startsWith("api/") ? DATA : SHELL));
  else event.respondWith(networkFirst(request, SHELL));
});
