"""Scan the AC server logs and compare their best laps with the open records file.

The logic behind the Best Laps tab.
"""
import os
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import log_best_laps as lbl
from check_track_records import is_blank

INTERVAL = 600


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


def _probe(logs_dir):
    if not os.path.isdir(logs_dir):
        raise LogsFolderError("not_found", "not found")
    try:
        with os.scandir(logs_dir):
            pass
    except OSError as exc:
        raise LogsFolderError("unreachable", f"({type(exc).__name__})") from exc


def scan(logs_dir, cache):
    """Read the logs in logs_dir that changed since the last scan and return all their laps.

    cache is {log name: (signature, laps)} and is updated in place. Returns
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
    return [lap for name in sorted(cache) for lap in cache[name][1]], len(changed), unreadable


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
    """One BestLap per (track, layout, car): the fastest lap, the first one on a tie."""
    data = {}
    details = {}
    for track_id, layout_id, car_id, driver, ms in laps:
        unmapped = set()
        track, layout, car = lbl.resolve_names(id_map, track_id, layout_id, car_id, unmapped)
        if lbl.merge_lap(data, track, layout, car, driver, ms):
            matched = (not unmapped and f"{track}::{layout}" in catalog_tracks
                       and car in catalog_cars)
            details[(track, layout, car)] = (f"{track_id} / {layout_id} / {car_id}", matched)
    rows = []
    for track, layouts in data.items():
        for layout, entry in layouts.items():
            for record in entry["records"]:
                raw, matched = details[(track, layout, record["car"])]
                rows.append(BestLap(track, layout, record["car"], record["driver"],
                                    lbl.parse_time(record["time"]), raw, matched))
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
        return "beats"
    return "ties" if row.ms == fastest else "trails"


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
