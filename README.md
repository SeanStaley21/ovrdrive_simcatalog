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
- `db/userSetRecords.json` — lap times set on the rigs, grouped by track then layout; where records set on the rigs are entered and what the Records page shows (see "Rig records" below).
- `db/track-records.json` — seeded real-world lap records per `"Track::Layout"` key, checked by `tools/check_track_records.py` (see "Track records" below). Not read by the site yet.
- `css/main.css`, `css/mobile.css` — desktop and mobile styles.
- `css/popups.css` — car and track popup styles.
- `css/tiles.css` — car and track tile styles.
- `css/records.css` — styles for the Records page.
- `rigRecords/records.js` — the Records page (search, class filters, expandable track list).
- `cars/` — car photos referenced by the catalog data.
- `tracks/` — track layout images (each track has a filled and an outline version per layout).
- `thumbs/` — WebP card thumbnails generated from the car and track images by `tools/make_thumbs.py`.
- `tools/` — maintenance scripts, including the Records editor (`records_editor.py`, `records_file.py`, `test_records_file.py`, `build_records_editor.bat`) and `log_best_laps.py`, which keeps the best lap per track, layout and car from the Assetto Corsa server logs (see "Best laps from the server logs" in `db/README.md`).
- `logos/` — OVRDRIVE branding assets.
- `favicon.png` — site favicon.
- `manifest.webmanifest`, `icons/` — web app manifest and its 192/512 px install icons.
- `sw.js` — service worker that makes the catalog installable and available offline.
- `qr codes/` — printable/TV QR codes linking to the catalog.
- `car stuff/`, `track stuff/` — working files (CSVs, notes, source photos) used to build/update the catalog data; not served by the site.

## Updating data

Car and track entries live in `data/cars.json` and `data/tracks.json`. Edit the JSON and drop the corresponding image into `cars/` or `tracks/`; cards, brand dividers and counts update automatically. A new brand also needs a sidebar button in `index.html`.

After adding, replacing, renaming or removing a car or track image, run `python tools/make_thumbs.py` (requires Pillow) to refresh `thumbs/`. Card grids load `thumbs/<image path without extension>.webp`; popups use the full image.

### Rig records

The Records page in the top bar reads `db/userSetRecords.json`. It lists every track in `data/tracks.json` alphabetically, and each track holds its layouts, each with one blank record. To add a time, type between the quotes of the blank record:

```
{ "class": "GT", "car": "Porsche 911 GT3 R", "driver": "Sean", "time": "1:42.315" }
```

`class` is one of `Formula`, `Prototype`, `GT`, `Stock car` (shown on the page as Formula 1, LMP, GT, NASCAR). `time` is `m:ss.mmm`. An optional `year` is shown next to the car (it must match the year of `date` when both are set); an optional `date` (`YYYY-MM-DD`) is shown in its place when present. Entries are ranked fastest first within each class. Blank records are ignored, and a half-filled record fails the check. See `db/README.md` for a second record, the other fields and the VS Code fold shortcuts. Then run the check:

```
python tools/check_track_records.py
```

Records can also be added with the Records editor app (`tools/records_editor.py`, or the built `OVRDrive Records Editor.exe`); see the "Records editor" section in `db/README.md`.

Edits to this file go live without bumping `VERSION`: the service worker fetches it from the network first and only falls back to its cached copy when offline. A track or layout that is not in `data/tracks.json` is ignored and logged to the browser console.

### Track records

Seeded real-world lap records live in `db/track-records.json`, one entry per `"Track::Layout"` key. Only `class`, `car`, `driver` and `time` are required per record; see `db/README.md` for the fields and allowed values. Before committing an edit to either records file, run:

```
python tools/check_track_records.py
```

## Offline / install

The catalog is an installable web app. `sw.js` precaches the page, CSS, JS, data files, icons and header logo, and caches car and track images the first time they are viewed, so previously viewed content works offline. Cached files other than `db/userSetRecords.json` are served without revalidating, so a deploy only reaches returning visitors when `VERSION` in `sw.js` changes. `db/userSetRecords.json` is fetched from the network first and falls back to the cached copy only when offline.

**Versioning rule:** bump `VERSION` in `sw.js` (to match the `?v=` values in `index.html`) whenever a deploy changes, replaces or removes any file under `cars/`, `tracks/`, `thumbs/`, `logos/` or `icons/`, or any precached file (CSS, JS, data, manifest) other than `db/userSetRecords.json`. Image URLs carry no `?v=`, so a same-name replacement stays stale until `VERSION` changes.

See `claude-instructions.md` for the full add/edit workflow, and `deriving-car-track-stats.md` for how to pull real stat values out of raw Assetto Corsa car/track content folders.
