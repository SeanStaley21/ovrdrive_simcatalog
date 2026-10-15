"""Scan the AC server logs and compare their best laps with the open records file.

The logic behind the Best Laps tab.
"""
import json
import os
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import log_best_laps as lbl
from check_track_records import is_blank

INTERVAL = 600


class LogsFolderError(Exception):
    pass


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
        raise LogsFolderError("not found")
    try:
        with os.scandir(logs_dir):
            pass
    except OSError as exc:
        raise LogsFolderError(f"unreachable ({type(exc).__name__})") from exc


def scan(logs_dir, cache):
    """Read the logs in logs_dir that changed since the last scan and return all their laps.

    cache is {log name: (signature, laps)} and is updated in place. Returns
    (laps, number of logs read, [(log name, exception type name)] for unreadable logs).
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


def load_catalog_tracks(records_path):
    try:
        tracks_file = Path(records_path).parent.parent / "data" / "tracks.json"
        return set(json.loads(tracks_file.read_text(encoding="utf-8-sig"))["tracks"])
    except Exception:
        return set()


def load_editor_id_map(records_path):
    try:
        return lbl.load_id_map(Path(records_path).parent.parent / "tools" / "ac_id_map.json")
    except (OSError, ValueError):
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


def error_message(logs_dir, error):
    """Status text for a failed scan; error is the text of the LogsFolderError or other failure."""
    retry = f"Retrying every {INTERVAL // 60} min."
    if error == "not found":
        return f"Best laps: logs folder not found: {logs_dir}. {retry}"
    if error.startswith("unreachable "):
        return f"Best laps: cannot read logs folder {logs_dir} {error[len('unreachable '):]}. {retry}"
    return f"Best laps: {error}. {retry}"


def ok_message(checked, files, unreadable, id_map_found):
    """Status text for a finished scan; checked is the datetime the scan finished."""
    next_check = checked + timedelta(seconds=INTERVAL)
    text = f"Best laps: {files} logs read at {checked:%H:%M:%S} (next check about {next_check:%H:%M})"
    if unreadable:
        text += f", {len(unreadable)} unreadable"
    if not id_map_found:
        text += ", id map not found: all laps unmatched"
    return text
