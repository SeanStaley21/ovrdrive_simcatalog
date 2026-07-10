# Deriving Car & Track Stats from Assetto Corsa Content

The user keeps source car/track mod folders on a flash drive (not in this git repo — never copy the raw folders, `.kn5`, `.acd`, `.dds`, etc. into the repo). When given a path to one of those folders (e.g. `D:\example car data\<car_id>` or `D:\...\example track data\<track_id>`), read the specific files below directly from that external path, derive the field values, then follow the normal add/edit workflow in `claude-instructions.md` (which is the source of truth for *where* those values go in `index.html`).

This file is only about **where the raw numbers come from and how to convert them**. Validated against 6 example cars (`an_g56_camaro`, `ferrari_458_gt2`, `ferrari_laferrari`, `ks_ferrari_sf15t`, `ks_porsche_cayman_gt4_std`, `rss_hyperion_2020`) and 2 example tracks (`atlanta_motorsports_park`, `ks_laguna_seca`) on 2026-07-10.

## Cars

### Where to look
Read `<car_folder>/ui/ui_car.json`. That's the only human-readable source — the real physics (`engine.ini`, `drivetrain.ini`, `tyres.ini`, etc.) lives packed/encrypted inside `data.acd` and can't be read directly.

- Some cars also have `ui/dlc_ui_car.json` (an alternate/DLC-pack preview entry) — `ui_car.json` is the one to use.
- **Some cars ship with no `ui/` folder at all** (seen with `rss_hyperion_2020`). If `ui_car.json` is missing, there is no readable stat source for that car — don't guess numbers. Tell the user and ask them to supply the specs (or export them from Content Manager) instead of estimating.
- Treat placeholder values literally present in the JSON (`"--kg"`, `"--s 0-100"`, `"--km/h"`, `"0-100"`, `"0"`, `null`) as **unknown**, not as real zeros.

### Field mapping → `carStats` entry

| carStats field | Source | Rule |
|---|---|---|
| key / display name | `name` | Use verbatim as the `carStats` key — matches the site's existing convention exactly (verified: `an_g56_camaro`'s `"name": "NASCAR Garage56 - Chevy Camaro"` is the literal key already in `index.html`). |
| `hp` | `specs.bhp` | Strip units/text, round to an integer. AC's bhp figure is used as-is for `hp` — no conversion (verified: `787 bhp` → `hp: 787`). |
| `tq` | `specs.torque` | Strip units, parse the Nm number, **convert Nm → ft-lb**: `ft_lb = round(Nm * 0.737562)`. Verified exactly against the live catalog: `an_g56_camaro` torque `862Nm` → `636` ft-lb, which is the value already in `carStats["NASCAR Garage56 - Chevy Camaro"].tq`. |
| `drive` | `tags` | Look for `rwd`/`fwd`/`awd` in the tags array (case-insensitive) → `RWD`/`FWD`/`AWD`. If no drivetrain tag is present, don't guess from the description alone without flagging it — ask. |
| `diff` (1 Beginner / 2 Intermediate / 3 Pro) | judgment | **Not in the JSON — subjective.** Anchor off existing entries: street cars with a manual/road tire setup skew 1 (e.g. `Abarth 500 EsseEsse` = 1); race-prepped cars (sequential box, slicks, aero, `"race"` tag) skew 2–3; open-wheel/prototype/very high power or downforce skews 3 (e.g. NASCAR COT cars, GT40 GT1, Ferrari 499P LMH are all `diff: 3` in the current data). Pick by comparing tags/power/description to the closest existing cataloged car, don't invent a formula. |
| `df` (Grip 1–10), `ts` (Top Speed 1–10), `br` (Braking 1–10) | judgment | **Not in the JSON — subjective 0–10 rating bars**, independent of the `hp`/`tq` progress-bar scale (`HP_MAX=2000`, `TQ_MAX=900` only apply to those two bars). Calibrate relative to similar existing cars (tire type/slicks vs street, aero/downforce elements, brake type, real-world top speed) rather than computing from any single stat. Flag your picks to the user for a sanity check rather than asserting them as fact. |
| `img` | none in JSON | Not derivable from data — needs a curated photo. Best source is a skin's `skins/<name>/preview.jpg` (rendered turntable/livery shot); pick the default/first skin, then crop/resize to match the existing `cars/*.jpg` convention before saving into `cars/`. |

## Tracks

### Where to look
- **Single-layout track** (e.g. `ks_laguna_seca`): read `<track_folder>/ui/ui_track.json` directly.
- **Multi-layout track** (e.g. `atlanta_motorsports_park`): each layout has its own subfolder under `ui/` (`ui/forward/`, `ui/reverse/`, `ui/kart/`, etc. — names vary per track). Read `ui/<layout>/ui_track.json` per layout; there's no single combined file.

Track data is never packed/encrypted (no `.acd` equivalent for tracks) — everything needed is plaintext JSON.

### Field mapping → `trackData` entry (key: `"Track Name::Layout Name"`)

| trackData field | Source | Rule |
|---|---|---|
| key | `name` per layout + folder name | The base track name is usually consistent across layouts; the per-layout `name` sometimes already appends the layout (`"Atlanta Motorsports Park kart layout"`) and sometimes doesn't (the `forward` layout's `name` was just `"Atlanta Motorsports Park"`). Use the common track name as the left side, and the layout **folder name**, capitalized, as the right side — e.g. `"Atlanta Motorsports Park::Forward"`, `"::Kart"`, `"::Reverse"`. Cross-check against the `run` field (`normal`/`reverse`/`anti-clockwise`) if the folder name is ambiguous. |
| `length` | `length` | **Units are inconsistent between tracks — verified two different conventions in the same sample set**: `atlanta_motorsports_park` stores meters (`"3218"`), `ks_laguna_seca` stores kilometers (`"3.602"`). Heuristic: if the numeric value is ≥ 100, treat as meters (`÷ 1609.344`); if < 100, treat as km (`× 0.621371`); always sanity-check the resulting mileage against the track's known real-world length before trusting it — if it's obviously wrong, don't force the heuristic, ask instead. Format like the existing data: `"X.XX mi"`. |
| `country` | `country` | Direct copy. |
| `state` | `city` | `city` is often `"City , State"` (e.g. `"Dawsonville , Georgia"`) — split on the comma, trim, take the second part as `state`. If there's no comma, `state: ""`. |
| `diff` (1 Easy … 5 Extreme) | judgment | **Not in the JSON.** The user already keeps a calibration list in `track stuff/tracks that need to be adjusted for difficulty.txt` — use its named examples as anchors, e.g.: Easy → Magione, Yoshi Falls, Lime Rock Park, Red Bull Ring short, Indianapolis/Daytona ovals. Moderate → Daytona road course, Riverside, Monza '66, Le Mans '67, Willow Springs, Vallelunga, Tsukuba, Rockingham, Red Bull Ring GP, Okayama. Challenging → Barcelona-Catalunya, Brands Hatch, Imola, Laguna Seca, Mid-Ohio, Oulton Park, Road Atlanta, Watkins Glen, New Hampshire. Hard → Port Newark, Yas Marina, Pocono, Sportsdrome (both layouts), Martinsville, Bristol. Extreme → Zandvoort, Topanga Canyon. Place new tracks relative to the nearest of these. |
| `record` | none in JSON | Real-world lap record — never present in the AC files. Check `track stuff/track misc/default tracks for assetto corsa.csv` first (the user's own reference list of real lap records by track/layout); if the track/layout isn't listed there, use the existing convention of `"N/A"` rather than inventing a number. |
| `img` | `ui/<layout>/preview.png` | Copy this in almost as-is (rename to the repo's slug convention, resize/format to match existing `tracks/*.png` files) — unlike car photos, the track's own preview image is already the right shot. |
| `outline` | `ui/<layout>/outline.png` (or `outline_cropped.png` if present) | Same as `img` — copy/rename into `tracks/<slug>-outline.png`. |

Unused fields (present in `ui_track.json`/`ui_car.json` but not read by the site at all): `description`, `width`, `pitboxes`, `author`, `version`, `url`, `geotags`. Fine to ignore.

## Workflow reminder

1. User gives an external folder path (flash drive) for one car or track — never for content that should live in the repo.
2. Read only the specific JSON files above from that path; don't bulk-copy the folder.
3. Derive/convert the fields per the tables above, flagging anything subjective (`diff`, `df`, `ts`, `br`, `record`) as a judgment call rather than presenting it as extracted fact.
4. Follow `claude-instructions.md` for the actual edit (both the JS data object *and* the matching HTML `.ce` entry — it's a two-places-to-edit model).
5. Save only the final curated image (car photo / track preview+outline) into `cars/`/`tracks/` — nothing else from the source folder gets committed.
