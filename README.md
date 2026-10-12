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
- `data/rig-records.json` — lap times set on the rigs, one list per `"Track::Layout"` key (see "Rig records" below).
- `css/main.css`, `css/mobile.css` — desktop and mobile styles.
- `css/popups.css` — car and track popup styles.
- `css/tiles.css` — car and track tile styles.
- `css/records.css` — styles for the Records page.
- `rigRecords/records.js` — the Records page (search, class filters, expandable track list).
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

### Rig records

The Records page in the top bar reads `data/rig-records.json`. It has one key per `"Track::Layout"` in `data/tracks.json`, each holding a list of times (empty until a time is set). To add a time:

1. Open `data/rig-records.json` and find the `"Track::Layout"` key.
2. Add an entry inside its `[]`, with commas between entries and none after the last:

```
{"class":"GT","car":"Porsche 911 GT3 R","driver":"Sean","time":"1:42.315","date":"10-12-2026"}
```

   `class` is one of `Formula 1`, `LMP`, `GT`, `NASCAR`. `time` is `m:ss.mmm`. `date` is `mm-dd-yyyy` and is shown as typed. Entries are ranked fastest first within each class.
3. Check the file is still valid JSON:

```
node -e "JSON.parse(require('fs').readFileSync('data/rig-records.json','utf8'))"
```

Edits to this file go live without bumping `VERSION`: the service worker fetches it from the network first and only falls back to its cached copy when offline. A key that is not in `data/tracks.json` is ignored and logged to the browser console.

## Offline / install

The catalog is an installable web app. `sw.js` precaches the page, CSS, JS, data files, icons and header logo, and caches car and track images the first time they are viewed, so previously viewed content works offline. Cached files other than `data/rig-records.json` are served without revalidating, so a deploy only reaches returning visitors when `VERSION` in `sw.js` changes. `data/rig-records.json` is fetched from the network first and falls back to the cached copy only when offline.

**Versioning rule:** bump `VERSION` in `sw.js` (to match the `?v=` values in `index.html`) whenever a deploy changes, replaces or removes any file under `cars/`, `tracks/`, `logos/` or `icons/`, or any precached file (CSS, JS, data, manifest) other than `data/rig-records.json`. Image URLs carry no `?v=`, so a same-name replacement stays stale until `VERSION` changes.

See `claude-instructions.md` for the full add/edit workflow, and `deriving-car-track-stats.md` for how to pull real stat values out of raw Assetto Corsa car/track content folders.
