# OVRDRIVE Sim Catalog

A single-page catalog of every car and track available in OVRDRIVE's racing simulators (Full Throttle Adrenaline Park). Built as a static site — no build step, no backend, no dependencies to install.

## Running it

Serve the folder with any static file server, e.g.:

```
npx serve .
```

The catalog loads its data with `fetch()`, so opening `index.html` directly (`file://`) will not work — use a local server. GitHub Pages is unaffected.

## Structure

- `index.html` — the app: markup, style hooks, and JS. Cards, brand dividers and counts are rendered at load time from the JSON data files.
- `data/cars.json`, `data/tracks.json` — all car and track data (stats, categories, brands, images, layouts, variant groups).
- `css/main.css`, `css/mobile.css` — desktop and mobile styles.
- `css/popups.css` — car and track popup styles.
- `css/tiles.css` — car and track tile styles, loaded last.
- `cars/` — car photos referenced by the catalog data.
- `tracks/` — track layout images (each track has a filled and an outline version per layout).
- `logos/` — OVRDRIVE branding assets.
- `favicon.png` — site favicon.
- `manifest.webmanifest`, `icons/` — web app manifest and its 192/512 px install icons.
- `sw.js` — service worker that makes the catalog installable and available offline.
- `qr codes/` — printable/TV QR codes linking to the catalog.
- `car stuff/`, `track stuff/` — working files (CSVs, notes, source photos) used to build/update the catalog data; not served by the site.

## Updating data

Car and track entries live in `data/cars.json` and `data/tracks.json`. Edit the JSON and drop the corresponding image into `cars/` or `tracks/`; cards, brand dividers and counts update automatically. A new brand also needs a sidebar button in `index.html`.

## Offline / install

The catalog is an installable web app. `sw.js` precaches the page, CSS, data files, icons and header logo, and caches car and track images the first time they are viewed, so previously viewed content works offline. Cached files are served without revalidating, so a deploy only reaches returning visitors when `VERSION` in `sw.js` changes.

**Versioning rule:** bump `VERSION` in `sw.js` (to match the `?v=` values in `index.html`) whenever a deploy changes, replaces or removes any file under `cars/`, `tracks/`, `logos/` or `icons/`, or any precached file (CSS, data, manifest). Image URLs carry no `?v=`, so a same-name replacement stays stale until `VERSION` changes.

See `claude-instructions.md` for the full add/edit workflow, and `deriving-car-track-stats.md` for how to pull real stat values out of raw Assetto Corsa car/track content folders.
