# db/

## track-records.json

Lap records per track. Not read by the site yet; edit it by hand and run the check before committing.

### Layout

One entry per `"Track::Layout"` key from `data/tracks.json`, kept in alphabetical order by track, then layout. Every track has an entry; a track with no records has an empty list.

```json
"Track::Layout": {
  "records": [ ...records... ],
  "no_record_reason": "optional note on why the list is empty"
}
```

### Record fields

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

Paste this into the `records` list of the track, with a comma between records:

```json
{ "class": "GT", "car": "Porsche 911 GT3 R", "driver": "Jane Doe", "time": "1:20.942" }
```

A track with no records looks like this:

```json
"Track::Layout": { "records": [] }
```

### Checking

```
python tools/check_track_records.py
```

Prints each problem as `Track::Layout: problem` and exits 1, or prints `OK: ...` and exits 0. An entry order that is not alphabetical only prints a warning. To check another file, pass its path as an argument.
