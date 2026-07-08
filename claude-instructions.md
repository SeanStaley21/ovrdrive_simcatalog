# Claude Instructions — OVRDRIVE Sim Catalog

There is no build step and no generator script. `index.html` is hand-edited directly, and it holds data in **two different places** that both have to be kept in sync by hand:

1. Two JS objects near the bottom of `index.html` (inside `<script>` tags) — the actual data (stats, images, difficulty).
2. Static HTML entries (sidebar buttons, brand dividers, category grids, count numbers) — what actually renders and is filterable.

If you only touch the JS object, the card won't appear anywhere. If you only touch the HTML entry, the card will render blank (name only, no image/stats) because the JS looks up the entry by exact key match and bails out silently if it's missing. **Every addition needs both.**

## Data model

- `carStats` (search `var carStats=`) — keyed by exact car name, e.g. `"Abarth 500 EsseEsse"`. Fields: `hp`, `tq` (torque), `drive` (`RWD`/`FWD`/`AWD`), `diff` (1=Beginner, 2=Intermediate, 3=Pro), `df` (grip), `ts` (top speed), `br` (braking) — `df`/`ts`/`br` are on a 0–10 scale, `img` (path into `cars/`).
- `trackData` (search `var trackData=`) — keyed by `"Track Name::Layout Name"` (layout name equals track name for tracks with only one layout). Fields: `record`, `diff` (1=Easy … 5=Extreme), `country`, `state`, `length`, `img` (into `tracks/`), `outline` (the outline PNG variant into `tracks/`).
- `trackLayouts` (search `var trackLayouts=`) — `{category: {trackName: [layoutName, ...]}}`. This is what groups layouts under one track card and decides which category tab(s) a track shows up in. A track can appear in more than one category (e.g. a speedway with both an oval and a road-course layout).

## Adding a new car

1. Add the photo to `cars/` — lowercase, hyphen-separated filename matching the existing naming style.
2. Add an entry to `carStats` with the exact name you want displayed as the key.
3. Add a `.ce` entry inside `#sec-all`'s grid, under the correct alphabetical brand `.bdiv` block (find the brand's `<div class="bdiv">BRANDNAME<span class="bdiv-count">N</span></div>` divider):
   ```html
   <div class="ce" data-car="Exact Name From carStats" data-brand="Brand" data-has-stats="1"><span class="cn">Exact Name From carStats</span></div>
   ```
   `data-car` must match the `carStats` key exactly, including case.
4. If the car is a new brand: add a `<button class="brand-btn" data-brand="Brand">Brand</button>` to `#brand-list` (alphabetical), and add a new `.bdiv` divider in `#sec-all` in alphabetical position.
5. If the car belongs to a category tab (GT3/GTE, Formula, Prototype/LMP, NASCAR, Drift, Fun & Novelty), add a matching `.ce` entry (same `data-car`/`data-has-stats`, no `data-brand`) into that `#sec-<category>` section's grid — `sec-gt3`, `sec-formula`, `sec-prototype`, `sec-nascar`, `sec-drift`, `sec-fun`.
6. Update the manual counts: the `#sec-all` header (`N CARS`), the brand's `.bdiv-count`, and the category section's count if you added one there.

## Adding a new track

1. Add both images to `tracks/`: the filled version and the `-outline` version, e.g. `track-name-layout.png` / `track-name-layout-outline.png`.
2. Add an entry to `trackData` keyed `"Track Name::Layout Name"`.
3. Add the layout name to `trackLayouts[category][trackName]` (create the track's array, or the category key, if new). Add it to more than one category's map if the track legitimately has layouts in multiple categories.
4. Add a `.ce` entry into `#trk-all`'s grid **and** into each relevant `#trk-<category>` section (`trk-road`, `trk-oval`, `trk-street`, `trk-fun-track`, `trk-drift-track`):
   ```html
   <div class="ce" data-tname="Track Name" data-tcat="road" data-country="USA" style="cursor:pointer"><span class="cn">Track Name</span></div>
   ```
   One `.ce` per track per category it appears in (not per layout — layouts are grouped automatically via `trackLayouts`).
5. Update the `N TRACKS` count in every section header you touched.
6. Sort order within category sections is computed automatically by difficulty at load time — don't manually reorder track cards.

## Adjusting stats or difficulty on an existing entry

- Cars: edit the object literal for that key in `carStats`.
- Tracks: edit the object literal(s) in `trackData`. If a track has multiple layouts, each `"Track::Layout"` key has its own `diff` — update all of them if the whole track's difficulty is changing, or just the one layout if it's layout-specific.
- `track stuff/tracks that need to be adjusted for difficulty.txt` is a scratch planning list, not read by the site — when you action an item from it, make the corresponding `trackData` edit and consider trimming the line from the file so it doesn't get redone.

## Renaming or removing a car/track

- Remove/rename the key in `carStats`/`trackData` (and `trackLayouts` for tracks).
- Remove/rename every matching `.ce` element — cars: `#sec-all` plus any category section; tracks: `#trk-all` plus every category section it was in.
- Update the counts you touched.
- Delete the now-unused image file(s) from `cars/`/`tracks/` if nothing else references them.

## Scratch/reference files (not read by the site, safe to leave stale but nice to update)

- `car stuff/car categories.csv`, `car stuff/list of all cars.txt` — human reference lists of cars.
- `track stuff/tracks that need to be adjusted for difficulty.txt` — difficulty rebalancing worklist.
- `car catalog fixes.txt` — general to-do notes.

These are working notes the user maintains alongside the catalog; treat them as planning input, not as a data source to sync from automatically.

## Verifying a change

After editing, open `index.html` in a browser (or `npx serve .`) and check:
- The new/changed card appears in the right place(s) with image, stats, and correct filter behavior (brand, category, difficulty, drivetrain for cars; category, country, difficulty for tracks).
- Clicking the card opens the detail view with correct data.
- The count shown in each section header matches the number of visible cards.

## Final check on large additions: spin up a review subagent

For any large batch of additions — a bulk import of many cars and/or tracks in one sitting, not a single one-off add — after finishing the edits, launch a subagent (general-purpose) to independently re-verify the change before calling it done. Don't rely solely on your own pass, since it's easy to lose track of one missed `.ce` entry or count across dozens of edits.

Give the subagent:
- The list of car/track names that were supposed to be added or changed in this batch.
- A pointer to this file (`claude-instructions.md`) for the data model and the two-source-of-truth rule.
- Instructions to check, for each added/changed entry:
  - It has a `carStats`/`trackData` (and `trackLayouts`, for tracks) entry with all required fields filled in (no placeholder/zero values left by mistake).
  - It has a matching `.ce` HTML entry in every section it should appear in (`sec-all` + brand bucket, and any category sections for cars; `trk-all` + every relevant category section for tracks), with `data-car`/`data-tname` spelled exactly like the data-object key.
  - The referenced image file(s) actually exist in `cars/` or `tracks/` (including the `-outline` PNG for tracks).
  - Section/brand counts (`N CARS` / `N TRACKS` / `.bdiv-count`) were updated to match the new totals.
- Instructions to report back a punch list of anything missing or mismatched, rather than fixing it directly — you make the fixes so the diff stays understood.

Treat the subagent's findings as required fixes before reporting the batch complete.
