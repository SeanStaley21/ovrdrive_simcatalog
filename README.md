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
- `cars/` — car photos referenced by the catalog data.
- `tracks/` — track layout images (each track has a filled and an outline version per layout).
- `logos/` — OVRDRIVE branding assets.
- `favicon.png` — site favicon.
- `qr codes/` — printable/TV QR codes linking to the catalog.
- `car stuff/`, `track stuff/` — working files (CSVs, notes, source photos) used to build/update the catalog data; not served by the site.

## Updating data

Car and track entries live in `data/cars.json` and `data/tracks.json`. Edit the JSON and drop the corresponding image into `cars/` or `tracks/`; cards, brand dividers and counts update automatically. A new brand also needs a sidebar button in `index.html`.

See `claude-instructions.md` for the full add/edit workflow, and `deriving-car-track-stats.md` for how to pull real stat values out of raw Assetto Corsa car/track content folders.
