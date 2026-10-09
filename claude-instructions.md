# Claude Instructions — OVRDRIVE Sim Catalog

If the user hands you a path to a raw Assetto Corsa car/track content folder (usually on a flash drive) and wants stats derived from it, see `deriving-car-track-stats.md` first — it covers where the real numbers live in that source data and how to convert them. This file covers what to do with those values once you have them.

There is no build step. All car and track data lives in two JSON files, and `index.html` renders the cards, brand dividers and counts from them at load time:

- `data/cars.json` — cars and variant groups.
- `data/tracks.json` — track stats, layouts and the track card lists.

**Edit the JSON only.** Do not add `.ce` cards, `.bdiv` dividers or count numbers to `index.html` — those are generated. (The sidebar brand/country/difficulty buttons in `index.html` are still hand-written; see "New brand" below.)

The page loads the JSON with `fetch()`, which does not work from `file://`. Always test through a server: `npx serve .`

## Data model

### `data/cars.json`
```
{ "cars": { "<exact car name>": { ... } }, "variantGroups": { ... } }
```
- Each car is keyed by its exact displayed name. Fields: `brand` (must match the sidebar `data-brand`), `hp`, `tq` (torque), `drive` (`RWD`/`FWD`/`AWD`), `diff` (1=Beginner, 2=Intermediate, 3=Pro), `df` (grip), `ts` (top speed), `br` (braking) — `df`/`ts`/`br` are on a 0–10 scale, `img` (path into `cars/`).
- `cats` (optional): list of category tabs the car also appears in — any of `gt3`, `formula`, `prototype`, `nascar`, `drift`, `fun`. Category tabs are sorted by name automatically.
- `hidden: true` (optional): the car has stats (used for variants) but gets no card of its own.
- **Order matters for the All Cars A–Z tab:** cars render in the order they appear in the file, and a brand divider is inserted whenever `brand` changes. Keep cars grouped by brand, brands alphabetical, cars alphabetical within the brand. A brand split into two runs would get two dividers.
- `variantGroups`: `{ "group-id": { "names": [carA, carB], "labels": ["Road Course", "Oval"] } }` — makes the popup show a toggle between variants. Use `hidden: true` on the variant that shouldn't have its own card.

### `data/tracks.json`
```
{ "tracks": {...}, "layouts": {...}, "sections": {...} }
```
- `tracks` — keyed by `"Track Name::Layout Name"` (layout name equals track name for tracks with only one layout). Fields: `record`, `diff` (1=Easy … 5=Extreme), `country`, `state`, `length`, `img` (into `tracks/`), `outline` (the outline PNG variant into `tracks/`).
- `layouts` — `{category: {trackName: [layoutName, ...]}}`. Groups layouts under one track card; the first layout is the default. A track can appear in more than one category (e.g. a speedway with both an oval and a road-course layout).
- `sections` — which track cards appear in each tab: keys `all`, `road`, `oval`, `street`, `fun-track`, `drift-track`, each a list of `{ "name", "cat", "country" }`. One card per track per category it appears in (not per layout). Category tabs are re-sorted by difficulty at load time, so order there doesn't matter.

## Adding a new car

1. Add the photo to `cars/` — lowercase, hyphen-separated filename matching the existing naming style.
2. Add an entry to `cars` in `data/cars.json`, in the right spot (brand group, alphabetical), with all fields and `brand` set. Add `cats` if it belongs to a category tab.
3. New brand only: add a `<button class="brand-btn" data-brand="Brand">Brand</button>` to `#brand-list` in `index.html` (alphabetical). The divider and counts are automatic.
4. Run `npx serve .` and check the car.

## Adding a new track

1. Add both images to `tracks/`: the filled version and the `-outline` version, e.g. `track-name-layout.png` / `track-name-layout-outline.png`.
2. Add an entry to `tracks` keyed `"Track Name::Layout Name"`.
3. Add the layout name to `layouts[category][trackName]` (create the track's array, or the category key, if new). Add it to more than one category if the track legitimately has layouts in multiple categories.
4. Add a `{ "name", "cat", "country" }` card to `sections.all` **and** to each relevant category list (`road`, `oval`, `street`, `fun-track`, `drift-track`). Header counts are automatic.
5. Run `npx serve .` and check the track.

## Adjusting stats or difficulty on an existing entry

- Cars: edit the fields on that car in `data/cars.json`.
- Tracks: edit the entry in `tracks`. If a track has multiple layouts, each `"Track::Layout"` key has its own `diff` — update all of them if the whole track's difficulty is changing, or just the one layout if it's layout-specific.
- `track stuff/tracks that need to be adjusted for difficulty.txt` is a scratch planning list, not read by the site — when you action an item from it, make the corresponding edit and consider trimming the line from the file so it doesn't get redone.

## Renaming or removing a car/track

- Cars: rename/remove the key in `data/cars.json` (and in `variantGroups` if it's listed there).
- Tracks: rename/remove the keys in `tracks`, the name in `layouts`, and every card in `sections`.
- Delete the now-unused image file(s) from `cars/`/`tracks/` if nothing else references them.
- Check the JSON is still valid (the page shows a load error if not).

## Scratch/reference files (not read by the site, safe to leave stale but nice to update)

- `car stuff/car categories.csv`, `car stuff/list of all cars.txt` — human reference lists of cars.
- `track stuff/tracks that need to be adjusted for difficulty.txt` — difficulty rebalancing worklist.
- `car catalog fixes.txt` — general to-do notes.

These are working notes the user maintains alongside the catalog; treat them as planning input, not as a data source to sync from automatically.

## Verifying a change

After editing, run `npx serve .` and check:
- The new/changed card appears in the right place(s) with image, stats, and correct filter behavior (brand, category, difficulty, drivetrain for cars; category, country, difficulty for tracks).
- Clicking the card opens the detail view with correct data.
- The browser console shows no errors (a typo in the JSON shows up there).

## Final check on large additions: spin up a review subagent

For any large batch of additions — a bulk import of many cars and/or tracks in one sitting, not a single one-off add — after finishing the edits, launch a subagent (general-purpose) to independently re-verify the change before calling it done.

Give the subagent:
- The list of car/track names that were supposed to be added or changed in this batch.
- A pointer to this file (`claude-instructions.md`) for the data model.
- Instructions to check, for each added/changed entry:
  - It has an entry in `data/cars.json` or `data/tracks.json` (and `layouts` plus every needed `sections` list, for tracks) with all required fields filled in (no placeholder/zero values left by mistake).
  - Cars have `brand` matching a sidebar button and sit in the correct brand group in the file.
  - The referenced image file(s) actually exist in `cars/` or `tracks/` (including the `-outline` PNG for tracks).
  - Both JSON files parse.
- Instructions to report back a punch list of anything missing or mismatched, rather than fixing it directly — you make the fixes so the diff stays understood.

Treat the subagent's findings as required fixes before reporting the batch complete.
