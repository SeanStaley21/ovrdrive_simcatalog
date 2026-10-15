"""Scan the AC server logs and compare their best laps with the open records file.

The logic behind the Best Laps tab.
"""
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import log_best_laps as lbl
from check_track_records import is_blank
from records_file import RecordsFileError, build_record, config_path

INTERVAL = 600
TOP_LAPS = 3


class LogsFolderError(Exception):
    """The logs folder cannot be scanned; kind is "not_found" or "unreachable"."""

    def __init__(self, kind, detail):
        super().__init__(detail)
        self.kind = kind


@dataclass
class BestLap:
    track: str
    layout: str
    car: str
    driver: str
    ms: int
    raw: str
    matched: bool
    date: str = ""
    ids: tuple = ()
    map_track: bool = False
    map_car: bool = False


def _probe(logs_dir):
    if not os.path.isdir(logs_dir):
        raise LogsFolderError("not_found", "not found")
    try:
        with os.scandir(logs_dir):
            pass
    except OSError as exc:
        raise LogsFolderError("unreachable", f"({type(exc).__name__})") from exc


def _modified_date(signature):
    return datetime.fromtimestamp(signature[1] // 10**9).strftime("%Y-%m-%d")


def scan(logs_dir, cache):
    """Read the logs in logs_dir that changed since the last scan and return all their laps.

    Each lap is the parsed lap plus the log file's modified date as YYYY-MM-DD and the log name. cache is {log name: (signature, laps)} and is updated in place. Returns
    (laps, number of logs re-read, [(log name, exception type name)] for unreadable logs).
    A log that cannot be read keeps the laps cached from its last good read.
    """
    logs_dir = Path(logs_dir)
    _probe(logs_dir)
    known = {name: signature for name, (signature, _) in cache.items()}
    signatures, changed, unreadable = lbl.read_changed_logs(logs_dir, known)
    if not signatures and not unreadable:
        _probe(logs_dir)
    fresh = {}
    for name, signature in signatures.items():
        laps = changed[name] if name in changed else cache[name][1]
        fresh[name] = (signature, laps)
    for name, _ in unreadable:
        if name in cache:
            fresh[name] = cache[name]
    cache.clear()
    cache.update(fresh)
    laps = [lap + (_modified_date(cache[name][0]), name) for name in sorted(cache) for lap in cache[name][1]]
    return laps, len(changed), unreadable


def load_editor_id_map(records_path):
    try:
        id_map = lbl.load_id_map(Path(records_path).parent.parent / "tools" / "ac_id_map.json")
        tracks, cars = id_map["tracks"], id_map["cars"]
        if not (isinstance(tracks, dict) and isinstance(cars, dict)):
            return None
        if not all(isinstance(car, str) for car in cars.values()):
            return None
        for track in tracks.values():
            if not isinstance(track, dict) or not isinstance(track.get("name", ""), str):
                return None
            layouts = track.get("layouts", {})
            if not (isinstance(layouts, dict) and all(isinstance(name, str) for name in layouts.values())):
                return None
        return id_map
    except Exception:
        return None


def resolve_lap(id_map, catalog_tracks, catalog_cars, matches, track_id, layout_id, car_id):
    """(track, layout, car, matched, map_track, map_car) for one lap's raw ids.

    The id map names a track, layout or car when it resolves into the catalog; otherwise a remembered
    manual match fills in. A part the id map does not know is matched only by a remembered match.
    """
    track, layout, car = lbl.resolve_names(id_map, track_id, layout_id, car_id, set())
    mapped_track = id_map["tracks"].get(track_id)
    map_track = (mapped_track is not None and layout_id in mapped_track.get("layouts", {})
                 and f"{track}::{layout}" in catalog_tracks)
    map_car = car_id in id_map["cars"] and car in catalog_cars
    manual_track = None if map_track else matches["tracks"].get(track_id, {}).get(layout_id)
    if manual_track:
        track, layout = manual_track["track"], manual_track["layout"]
    manual_car = None if map_car else matches["cars"].get(car_id)
    if manual_car is not None:
        car = manual_car
    matched = ((map_track or (manual_track is not None and f"{track}::{layout}" in catalog_tracks))
               and (map_car or (manual_car is not None and car in catalog_cars)))
    return track, layout, car, matched, map_track, map_car


def best_laps(laps, id_map, catalog_tracks, catalog_cars, matches=None):
    """Up to TOP_LAPS BestLap rows per (track, layout, car): the fastest distinct times, the first lap on a tie.

    Each log is one race and each driver counts only with their fastest lap in it.
    """
    matches = matches or {"tracks": {}, "cars": {}}
    fastest = {}
    for index, (track_id, layout_id, car_id, driver, ms, date, log_name) in enumerate(laps):
        track, layout, car, matched, map_track, map_car = resolve_lap(
            id_map, catalog_tracks, catalog_cars, matches, track_id, layout_id, car_id)
        key = (log_name, driver, track, layout, car)
        if key not in fastest or ms < fastest[key][1].ms:
            fastest[key] = (index, BestLap(
                track, layout, car, driver, ms, f"{track_id} / {layout_id} / {car_id}", matched, date,
                (track_id, layout_id, car_id), map_track, map_car))
    found = {}
    for _, best in sorted(fastest.values(), key=lambda item: item[0]):
        key = (best.track, best.layout, best.car)
        if all(row.ms != best.ms for row in found.get(key, [])):
            found.setdefault(key, []).append(best)
    rows = []
    for key_rows in found.values():
        rows.extend(sorted(key_rows, key=lambda row: row.ms)[:TOP_LAPS])
    rows.sort(key=lambda row: (not row.matched, row.track.casefold(), row.layout.casefold(), row.ms))
    return rows


def catalog_layouts(catalog_tracks):
    """{track: sorted layouts} from the "track::layout" catalog keys."""
    layouts = {}
    for key in catalog_tracks:
        track, _, layout = key.partition("::")
        layouts.setdefault(track, []).append(layout)
    return {track: sorted(names) for track, names in layouts.items()}


def check_match(catalog_tracks, catalog_cars, track, layout, car):
    """The reason a manual match is not allowed, else None; track and layout, or car, may be None to skip them."""
    if track is not None:
        layouts = catalog_layouts(catalog_tracks)
        if track not in layouts:
            return "Choose a track from the catalog."
        if layout not in layouts[track]:
            return f"Choose a layout of {track} from the catalog."
    if car is not None and car not in catalog_cars:
        return "Choose a car from the catalog."
    return None

def marker(row, data):
    """How row compares with the fastest record for the same car on the same layout."""
    if not row.matched:
        return f"unmatched: {row.raw}"
    records = data.get(row.track, {}).get(row.layout, {}).get("records", [])
    times = [lbl.parse_time(rec.get("time")) for rec in records
             if not is_blank(rec) and rec.get("car") == row.car]
    times = [ms for ms in times if ms is not None]
    if not times:
        return "no record"
    fastest = min(times)
    if row.ms < fastest:
        return "beats current record"
    return "ties" if row.ms == fastest else "trails"


def duplicate_message(data, track, layout, car, time_text):
    """The refusal text when data already holds this car's time on the layout, else None."""
    ms = lbl.parse_time(time_text)
    records = data.get(track, {}).get(layout, {}).get("records", [])
    if any(isinstance(rec, dict) and rec.get("car") == car and lbl.parse_time(rec.get("time")) == ms
           for rec in records):
        return f"{car} already has {time_text} on {track} / {layout}. Dismiss it to hide it."
    return None


def handled_path():
    return config_path().with_name("best_laps_handled.json")


def read_handled():
    """Every added or dismissed lap as (track, layout, car, ms), plus a trailing True for an added one; unusable data gives []."""
    try:
        value = json.loads(handled_path().read_text(encoding="utf-8"))
    except Exception:
        return []
    entries = value.get("handled") if isinstance(value, dict) else None
    if not isinstance(entries, list):
        return []
    handled = []
    for entry in entries:
        if (isinstance(entry, dict)
                and all(isinstance(entry.get(key), str) for key in ("track", "layout", "car"))
                and isinstance(entry.get("ms"), int) and not isinstance(entry["ms"], bool)):
            added = (True,) if entry.get("added") is True else ()
            handled.append((entry["track"], entry["layout"], entry["car"], entry["ms"]) + added)
    return handled


def write_handled(handled):
    target = handled_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    entries = []
    for t, l, c, ms, *added in handled:
        entries.append({"track": t, "layout": l, "car": c, "ms": ms, **({"added": True} if added else {})})
    target.write_text(json.dumps({"handled": entries}), encoding="utf-8")


def migrate_handled(handled, laps, id_map, catalog_tracks, catalog_cars, old_matches, new_matches):
    """handled with the dismissed entries of laps whose names changed from old_matches to new_matches moved to the new names.

    Entries of added laps never move. A dismissed entry that an unchanged lap also uses is kept and the
    moved laps' new entries are added beside it.
    """
    moves, stays = {}, set()
    for track_id, layout_id, car_id, _, ms, *_ in laps:
        ids = (track_id, layout_id, car_id)
        old = resolve_lap(id_map, catalog_tracks, catalog_cars, old_matches, *ids)[:3] + (ms,)
        new = resolve_lap(id_map, catalog_tracks, catalog_cars, new_matches, *ids)[:3] + (ms,)
        if old == new:
            stays.add(old)
        elif new not in moves.setdefault(old, []):
            moves[old].append(new)
    migrated = []
    for entry in handled:
        if len(entry) > 4 or entry not in moves:
            results = [entry]
        else:
            results = ([entry] if entry in stays else []) + moves[entry]
        for result in results:
            if result not in migrated:
                migrated.append(result)
    return migrated


def is_handled(row, handled):
    """True when this exact lap time for the same car was already added or dismissed."""
    key = (row.track, row.layout, row.car, row.ms)
    return any(entry[:4] == key for entry in handled)


def matches_path():
    return config_path().with_name("best_laps_matches.json")


def read_matches():
    """The remembered manual matches {"tracks": {track id: {layout id: {"track", "layout"}}}, "cars": {car id: name}}; unusable data gives none."""
    matches = {"tracks": {}, "cars": {}}
    try:
        value = json.loads(matches_path().read_text(encoding="utf-8"))
    except Exception:
        return matches
    if not isinstance(value, dict):
        return matches
    tracks, cars = value.get("tracks"), value.get("cars")
    for track_id, layouts in (tracks.items() if isinstance(tracks, dict) else ()):
        for layout_id, entry in (layouts.items() if isinstance(layouts, dict) else ()):
            if (isinstance(entry, dict) and isinstance(entry.get("track"), str)
                    and isinstance(entry.get("layout"), str)):
                matches["tracks"].setdefault(track_id, {})[layout_id] = {
                    "track": entry["track"], "layout": entry["layout"]}
    for car_id, name in (cars.items() if isinstance(cars, dict) else ()):
        if isinstance(name, str):
            matches["cars"][car_id] = name
    return matches


def write_matches(matches):
    target = matches_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(matches), encoding="utf-8")


def lap_record(row, name, cls, date_text):
    """The record for row's lap, ready for records_file.add."""
    if not cls:
        raise RecordsFileError("Choose a class.")
    rec = build_record(cls, row.car, name, lbl.format_time(row.ms), "", date_text)
    rec["source"] = lbl.SOURCE
    return rec


def error_message(logs_dir, kind, detail):
    """Status text for a failed scan; kind is a LogsFolderError kind or "failed"."""
    retry = f"Retrying every {INTERVAL // 60} min."
    if kind == "not_found":
        return f"Best laps: logs folder not found: {logs_dir}. {retry}"
    if kind == "unreachable":
        return f"Best laps: cannot read logs folder {logs_dir} {detail}. {retry}"
    return f"Best laps: {detail}. {retry}"


def ok_message(checked, total, reread, unreadable, id_map_found):
    """Status text for a finished scan; checked is the datetime the scan finished."""
    next_check = checked + timedelta(seconds=INTERVAL)
    text = f"Best laps: {total} readable logs, {reread} re-read, checked at {checked:%H:%M:%S} (next check about {next_check:%H:%M})"
    if unreadable:
        text += f", {len(unreadable)} unreadable"
    if not id_map_found:
        text += ", id map missing or unusable: laps are unmatched unless matched manually"
    return text
