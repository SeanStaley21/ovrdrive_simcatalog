# OVRDRIVE Sim Catalog

A single-page catalog of every car and track available in OVRDRIVE's racing simulators (Full Throttle Adrenaline Park). Built as a static site — no build step, no backend, no dependencies to install.

## Running it

Just open `index.html` in a browser, or serve the folder with any static file server, e.g.:

```
npx serve .
```

## Structure

- `index.html` — the entire app: markup, styles hooks, and JS. Car and track data is embedded inline as JS objects (`carStats`, etc.), each entry pointing at an image file.
- `css/main.css`, `css/mobile.css` — desktop and mobile styles.
- `cars/` — car photos referenced by the catalog data.
- `tracks/` — track layout images (each track has a filled and an outline version per layout).
- `logos/` — OVRDRIVE branding assets.
- `favicon.png` — site favicon.
- `qr codes/` — printable/TV QR codes linking to the catalog.
- `car stuff/`, `track stuff/` — working files (CSVs, notes, source photos) used to build/update the catalog data; not served by the site.

## Updating data

Car and track entries live directly inside `index.html` (search for `carStats`). There's no separate database — edit the JS object literals and drop the corresponding image into `cars/` or `tracks/`.
