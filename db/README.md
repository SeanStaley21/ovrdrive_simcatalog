# db/

Two record files live here:

- `userSetRecords.json` is where records set on the rigs are entered. The Records page reads it.
- `track-records.json` is seeded reference data from outside sources; it can also be edited by hand and is checked the same way. Not read by the site yet.

## userSetRecords.json

Records set here, grouped by track, then layout. It lists every track in `data/tracks.json` in alphabetical order, and each track holds its layouts in alphabetical order. Every layout ships with one blank record:

```json
"Laguna Seca": {
  "Laguna Seca": {
    "records": [
      { "class": "", "car": "", "driver": "", "time": "" }
    ]
  }
}
```

To add a record, type between the quotes of the blank record. `class`, `car`, `driver` and `time` are required; the optional fields in the table below are added only when needed. For a second record on the same layout, copy the line and add a comma after the first:

```json
"records": [
  { "class": "GT", "car": "Porsche 911 GT3 R", "driver": "Jane Doe", "time": "1:20.942" },
  { "class": "", "car": "", "driver": "", "time": "" }
]
```

A record with all four required fields empty (and no other fields) is blank: the check and the site ignore it and it counts as no record. A half-filled record is an error.

The `class` value is stored as in the allowed list below; the Records page shows `Formula` as Formula 1, `Prototype` as LMP and `Stock car` as NASCAR. Records are ranked fastest first within each class.

In VS Code, Ctrl+K Ctrl+2 folds the file down to track names and Ctrl+K Ctrl+J unfolds everything. Ctrl+K Ctrl+3 shows the layouts under each track.

Edits to this file go live without bumping `VERSION`: the service worker fetches it from the network first.

## track-records.json

Seeded lap records per track. Not read by the site yet; edit it by hand and run the check before committing.

### Layout

One entry per `"Track::Layout"` key from `data/tracks.json`, kept in alphabetical order by track, then layout. Every track has an entry; a track with no records has an empty list.

```json
"Track::Layout": {
  "records": [ ...records... ],
  "no_record_reason": "optional note on why the list is empty"
}
```

### Record fields

These fields and the allowed values below apply to both files.

| Field | Required | Default | Notes |
| --- | --- | --- | --- |
| `class` | yes | | One of the allowed classes below |
| `car` | yes | | Text |
| `driver` | yes | | Text; use `"Unknown"` if not known |
| `time` | yes | | `m:ss.mmm` |
| `lap_type` | no | `unknown` | One of the allowed lap types below |
| `verified` | no | `false` | `true` or `false` |
| `confidence` | no | none | `exact layout` or `layout changed` |
| `year` | no | none | Whole number, e.g. `2019` |
| `source` | no | none | Text, usually a URL |
| `note` | no | none | Text |
| `speed_mph` | no | none | Number |

### Allowed values

`class`: Formula, GT, GT (GTE Am), Hillclimb, Mazda MX-5 Cup, Production road car, Prototype, Sports/Can-Am (historic), Stock car, Super GT GT300, Super GT GT500, Supercars, Time attack, Time trial (SCCA Time Trials), Trans Am TA, Trans Am TA1

`lap_type`: race, qualifying, track_record, unknown, demo, exhibition

`confidence`: exact layout, layout changed

To add a class, add it to `CLASSES` in `tools/check_track_records.py` and to the list above.

### Time format

`m:ss.mmm`, for example `1:20.942`. Laps under a minute are written `0:ss.mmm`, for example `0:28.074`. Times published with 1 to 4 decimals are accepted as published.

### Adding a record

Paste this into the `records` list of the entry, with a comma between records:

```json
{ "class": "GT", "car": "Porsche 911 GT3 R", "driver": "Jane Doe", "time": "1:20.942" }
```

A track with no records looks like this:

```json
"Track::Layout": { "records": [] }
```

### Checking

```
python tools/check_track_records.py                  # both files
python tools/check_track_records.py PATH             # one file shaped like track-records.json
python tools/check_track_records.py --nested PATH    # one file shaped like userSetRecords.json
```

With no arguments it checks `track-records.json` and `userSetRecords.json`. Each problem is printed with its track and layout. The exit code is 1 if any problem was found; otherwise each file prints `OK: ...` and the exit code is 0. A track or layout order that is not alphabetical only prints a warning.

## Best laps from the server logs

`tools/log_best_laps.py` reads the Assetto Corsa dedicated-server logs (`AC LAN Main Server_*.log`) and keeps one JSON file with the fastest lap per track, layout and car. The file has the nesting of `userSetRecords.json`; each record is:

```json
{ "class": "", "car": "Ferrari SF70H", "driver": "Pod 3", "time": "1:36.595", "source": "ac-server-log" }
```

`driver` is the pod name from the log and can be edited by hand; an edited record is kept until a faster lap beats it. `class` is left blank. Laps with cuts and the Spectator slot are skipped. Each log names one track, one layout and the cars, and both sessions in a log count.

```
python tools/log_best_laps.py --logs-dir "<Server Logs folder>"          # watch, rescan every 30 s
python tools/log_best_laps.py --logs-dir "<Server Logs folder>" --once   # one pass, then exit
```

Options: `--out` (default `bestLapsTest.json` next to the tool), `--map` (default `ac_id_map.json` next to the tool), `--interval` (seconds, default 30). The tool also writes `<out>.state.json`, which remembers the logs already read; deleting it is always safe. A records file that is not valid JSON of the right shape stops the tool without being overwritten.

`tools/ac_id_map.json` turns the ids in the logs into catalog names: `tracks` maps a track id to its catalog name and a `layouts` map from layout id (`""` when the log has no layout line) to catalog layout name, and `cars` maps a car id to its catalog name. An id with no entry is written under its raw id and named once in the console; add it to the map.

The output is not `userSetRecords.json`, and `python tools/check_track_records.py --nested FILE` reports the blank `class` and every catalog layout without records. Fill in `class` before moving records into `userSetRecords.json`.

To run it as a program, `tools/build_log_best_laps.bat` builds `tools/dist/log_best_laps.exe` with PyInstaller and copies `ac_id_map.json` next to it. Tests: `python -m unittest discover -s tools -p "test_*.py"`.
