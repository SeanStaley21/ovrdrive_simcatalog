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

## Records editor

A small Windows app for adding records to `userSetRecords.json` without editing the JSON by hand.

- Double-click `OVRDrive Records Editor.exe`. The first launch asks you to pick `db/userSetRecords.json` and remembers it in `%APPDATA%\OVRDrive Records Editor\config.json`. Delete that file, or use File > Change file..., to point it at a different file.
- Pick a track, then a layout, then fill Class, Car, Driver, Time and Year. Year defaults to the current year and must match the year of the Date when both are set. Date is optional (`YYYY-MM-DD`); to clear one, edit the record, empty the Date field and save.
- The Car box autocompletes from `data/cars.json` but accepts any text.
- Use New, Edit selected, Delete selected and Save.
- The app icon is drawn by `tools/make_records_editor_icon.py`; regenerate it with `python tools/make_records_editor_icon.py`.
- Save changes only the layout you touched, keeps the file's line endings and format, and adds records before the trailing blank record. It refuses files with duplicate keys or invalid JSON.
- Saving does not publish anything. Commit and push the changed file afterward.
- The exe is unsigned, so Windows SmartScreen may show "Windows protected your PC". Choose More info > Run anyway.

### Best Laps tab

The Best Laps tab lists the three fastest laps per track, layout and car from the Assetto Corsa server logs. A lap is written to `userSetRecords.json` only when you add it and confirm the prompt.

- The editor scans the logs folder when it starts and every 10 minutes while it is open. Check now scans straight away and is disabled while a scan runs. Logs that have not changed are not read again.
- On first use the editor asks for the logs folder. It is saved as `logs_dir` in the same `config.json` as the records file path. Use File > Set logs folder... to change it. Cancelling the first prompt turns scanning off until the next launch.
- Columns are Track, Layout, Car, Pod/Driver, Time and Status. There are up to three rows per track, layout and car, one for each of its three fastest lap times (a time shared by several laps counts once); laps with cuts and the Spectator slot are skipped, and a log that cannot be read is skipped.
- Status compares the lap with the fastest record for the same car on that layout in the open records file, any class: `beats current record`, `ties`, `trails` or `no record`. Record times that cannot be read, such as ones with four decimals, are ignored. After editing the file outside the editor, use File > Reload.
- Add... opens a prompt for each selected row, one after the other, with Name (prefilled with the pod name), Class (required, no default) and Date (prefilled with the log file's last-modified date, which you can edit; `YYYY-MM-DD`). Confirming saves all the selected laps in one write with `source` set to `ac-server-log`. Cancelling any prompt writes nothing, and leaving Class unchosen blocks the save. A lap that beats the current record is added next to it; the old record is untouched, and replacing it stays a manual edit on the Records tab.
- Only a car's three fastest laps are ever listed, and added or dismissed laps still use up one of those three slots.
- A row whose track and layout are not in the records file cannot be added; add the layout to the file first. An unmatched row must be matched first (see Match... below).
- Dismiss hides the selected rows (matched or not) without writing to `userSetRecords.json`. Added and dismissed laps stay hidden after a restart, but only for the exact lap time: a different lap time for the same car and layout, such as a new faster lap, shows as a new row. They are remembered in `best_laps_handled.json` next to `config.json` in `%APPDATA%\OVRDrive Records Editor\`; deleting that file is safe and brings the rows back.
- A lap whose track, layout or car is not in the id map, or whose names are not in `data/tracks.json` or `data/cars.json`, is grey and shows `unmatched:` with the raw ids (`track id / layout id / car id`). To fix it for everyone, add the ids to `tools/ac_id_map.json` or add the car or track to the catalog. To fix it on this computer only, select the row and use Match...
- Match... works on one unmatched row. It shows the raw ids and lets you pick the catalog Track, Layout and Car (type to filter the lists; the layouts are those of the chosen track). A part the id map already resolves is shown but cannot be changed. OK saves the match for those raw ids, so every lap with the same ids is matched, now and after a restart, and the row can then be added like any other. A match applies only to the log ids shown in the dialog, so another log id for the same catalog car needs its own match. Matching the same ids again replaces the earlier match, and several raw car ids can be matched to the same catalog car. Matches are remembered in `best_laps_matches.json` next to `config.json`; deleting that file removes them all. `tools/ac_id_map.json` is never changed, and when it resolves a track, layout or car into the catalog it wins over a remembered match. A lap dismissed while it was unmatched stays dismissed after you match it, and matching again moves only dismissed laps with it. A lap added from the tab stays hidden under the names it was added with, so correcting a wrong match brings the lap back as a new row under the corrected names; the record already added stays in `userSetRecords.json` and must be removed by hand on the Records tab. A row matched this way looks like any other matched row.
- The status bar line "Best laps: ..." shows when the last check ran and when the next is due. If the logs folder is missing or cannot be read it says so and tries again every 10 minutes, and the rows from the last good scan stay. "id map missing or unusable" means `tools/ac_id_map.json` is missing from the repo that holds the records file or is not a valid id map, so laps are unmatched unless they were matched manually. "readable logs" counts logs that have been read successfully; unreadable ones are counted separately.

Run from source:

```
python tools/records_editor.py
```

Run the tests:

```
python -m unittest discover -s tools -p "test_*.py"
```

Build the exe:

```
pip install pyinstaller
tools\build_records_editor.bat
```

The output is `dist\OVRDrive Records Editor.exe`. It is not committed; publish it as a GitHub Release asset.

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
| `date` | no | none | Real calendar date written `YYYY-MM-DD`, e.g. `2026-10-12`; may sit beside `year`, whose value must equal the date's year |
| `source` | no | none | Text, usually a URL; `ac-server-log` for laps added from the server logs |
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

The Records editor's Best Laps tab uses the same parser and id map, and can add these laps to `userSetRecords.json` with `source` `"ac-server-log"`.

`driver` is the pod name from the log and can be edited by hand; an edited record is kept until a faster lap beats it. `class` is left blank. Laps with cuts and the Spectator slot are skipped. Each log names one track, one layout and the cars, and both sessions in a log count.

```
python tools/log_best_laps.py --logs-dir "<Server Logs folder>"          # watch, rescan every 30 s
python tools/log_best_laps.py --logs-dir "<Server Logs folder>" --once   # one pass, then exit
```

Options: `--out` (default `bestLapsTest.json` next to the tool), `--map` (default `ac_id_map.json` next to the tool), `--interval` (seconds, default 30). The tool also writes `<out>.state.json`, which remembers the logs already read; deleting it is always safe. A records file that is not valid JSON of the right shape stops the tool without being overwritten.

`tools/ac_id_map.json` turns the ids in the logs into catalog names: `tracks` maps a track id to its catalog name and a `layouts` map from layout id (`""` when the log has no layout line) to catalog layout name, and `cars` maps a car id to its catalog name. An id with no entry is written under its raw id and named once in the console; add it to the map.

The output is not `userSetRecords.json`, and `python tools/check_track_records.py --nested FILE` reports the blank `class` and every catalog layout without records. Fill in `class` before moving records into `userSetRecords.json`.

Tests: `python -m unittest discover -s tools -p "test_*.py"`.
