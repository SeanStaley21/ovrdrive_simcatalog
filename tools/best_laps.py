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

    Each lap is the parsed lap plus the log file's modified date as YYYY-MM-DD. cache is {log name: (signature, laps)} and is updated in place. Returns
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
    laps = [lap + (_modified_date(cache[name][0]),) for name in sorted(cache) for lap in cache[name][1]]
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


def best_laps(laps, id_map, catalog_tracks, catalog_cars):
    """Up to TOP_LAPS BestLap rows per (track, layout, car): the fastest distinct times, the first lap on a tie."""
    found = {}
    for track_id, layout_id, car_id, driver, ms, date in laps:
        unmapped = set()
        track, layout, car = lbl.resolve_names(id_map, track_id, layout_id, car_id, unmapped)
        matched = (not unmapped and f"{track}::{layout}" in catalog_tracks
                   and car in catalog_cars)
        key = (track, layout, car)
        if all(row.ms != ms for row in found.get(key, [])):
            found.setdefault(key, []).append(BestLap(
                track, layout, car, driver, ms, f"{track_id} / {layout_id} / {car_id}", matched, date))
    rows = []
    for key_rows in found.values():
        rows.extend(sorted(key_rows, key=lambda row: row.ms)[:TOP_LAPS])
    rows.sort(key=lambda row: (not row.matched, row.track.casefold(), row.layout.casefold(), row.ms))
    return rows


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


def handled_path():
    return config_path().with_name("best_laps_handled.json")


def read_handled():
    """The (track, layout, car, ms) of every added or dismissed lap; unusable data gives []."""
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
            handled.append((entry["track"], entry["layout"], entry["car"], entry["ms"]))
    return handled


def write_handled(handled):
    target = handled_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    entries = [{"track": t, "layout": l, "car": c, "ms": ms} for t, l, c, ms in handled]
    target.write_text(json.dumps({"handled": entries}), encoding="utf-8")


def is_handled(row, handled):
    """True when this exact lap time for the same car was already added or dismissed."""
    return (row.track, row.layout, row.car, row.ms) in handled


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
        text += ", id map missing or unusable: all laps unmatched"
    return text
