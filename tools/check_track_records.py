"""Check db/track-records.json for the mistakes hand editing causes.

Usage: python tools/check_track_records.py [path/to/track-records.json]
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RECORDS = ROOT / "db" / "track-records.json"
TRACKS = ROOT / "data" / "tracks.json"

CLASSES = [
    "Formula",
    "GT",
    "GT (GTE Am)",
    "Hillclimb",
    "Mazda MX-5 Cup",
    "Production road car",
    "Prototype",
    "Sports/Can-Am (historic)",
    "Stock car",
    "Super GT GT300",
    "Super GT GT500",
    "Supercars",
    "Time attack",
    "Time trial (SCCA Time Trials)",
    "Trans Am TA",
    "Trans Am TA1",
]
LAP_TYPES = ["race", "qualifying", "track_record", "unknown", "demo", "exhibition"]
CONFIDENCES = ["exact layout", "layout changed"]
TIME_RE = re.compile(r"^\d+:[0-5]\d\.\d{1,4}$")

REQUIRED = ["class", "car", "driver", "time"]
OPTIONAL = ["lap_type", "year", "source", "confidence", "verified", "speed_mph", "note"]
ENTRY_FIELDS = ["records", "no_record_reason"]


class DuplicateTracker:
    """object_pairs_hook that remembers which keys appeared twice in which object."""

    def __init__(self):
        self.duplicates = {}

    def __call__(self, pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                self.duplicates.setdefault(id(obj), []).append(key)
            obj[key] = value
        return obj


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def sort_key(key):
    return tuple(part.casefold() for part in key.split("::"))


def check_record(rec, label, problems, duplicates):
    if not isinstance(rec, dict):
        problems.append(f"{label}: record is not an object")
        return
    for field in duplicates.get(id(rec), []):
        problems.append(f"{label}: duplicate field '{field}'")
    for field in REQUIRED:
        value = rec.get(field)
        if field not in rec:
            problems.append(f"{label}: missing required field '{field}'")
        elif not isinstance(value, str) or not value.strip():
            problems.append(f"{label}: '{field}' must be a non-empty string")
    for field in rec:
        if field not in REQUIRED and field not in OPTIONAL:
            problems.append(f"{label}: unknown field '{field}'")
    time = rec.get("time")
    if isinstance(time, str) and time.strip() and not TIME_RE.match(time):
        problems.append(f"{label}: time '{time}' must look like m:ss.mmm (e.g. 1:20.942)")
    for field, allowed in (("class", CLASSES), ("lap_type", LAP_TYPES), ("confidence", CONFIDENCES)):
        if field == "class" and not (isinstance(rec[field], str) and rec[field].strip()):
            continue
        if field in rec and rec[field] not in allowed:
            problems.append(f"{label}: {field} '{rec[field]}' is not allowed; use one of: {', '.join(allowed)}")
    if "verified" in rec and not isinstance(rec["verified"], bool):
        problems.append(f"{label}: 'verified' must be true or false")
    if "year" in rec and (not isinstance(rec["year"], int) or isinstance(rec["year"], bool)):
        problems.append(f"{label}: 'year' must be a whole number")
    if "speed_mph" in rec and not is_number(rec["speed_mph"]):
        problems.append(f"{label}: 'speed_mph' must be a number")
    for field in ("source", "note"):
        if field in rec and not isinstance(rec[field], str):
            problems.append(f"{label}: '{field}' must be a string")


def check_data(data, track_keys, duplicates):
    problems = []
    warnings = []
    records = 0
    if not isinstance(data, dict):
        return ["top level must be an object keyed by Track::Layout"], warnings, 0, 0
    for key in duplicates.get(id(data), []):
        problems.append(f"{key}: duplicate track key")
    for key, entry in data.items():
        if key not in track_keys:
            problems.append(f"{key}: not a track in data/tracks.json")
        if not isinstance(entry, dict):
            problems.append(f"{key}: entry must be an object like {{\"records\": []}}")
            continue
        for field in duplicates.get(id(entry), []):
            problems.append(f"{key}: duplicate entry field '{field}'")
        for field in entry:
            if field not in ENTRY_FIELDS:
                problems.append(f"{key}: unknown entry field '{field}'")
        recs = entry.get("records")
        if not isinstance(recs, list):
            problems.append(f"{key}: 'records' is missing or not a list")
            continue
        if "no_record_reason" in entry and not isinstance(entry["no_record_reason"], str):
            problems.append(f"{key}: 'no_record_reason' must be a string")
        for n, rec in enumerate(recs, 1):
            records += 1
            check_record(rec, f"{key} record {n}", problems, duplicates)
    for key in track_keys:
        if key not in data:
            problems.append(f'{key}: missing; add {{"records": []}}')
    keys = list(data)
    for prev, cur in zip(keys, keys[1:]):
        if sort_key(prev) > sort_key(cur):
            warnings.append(f"{cur}: out of order (should come before {prev})")
    return problems, warnings, len(data), records


def nearest_key(text, line):
    for text_line in reversed(text.splitlines()[: max(line - 1, 0)]):
        match = re.match(r'^\s*"([^"]+::[^"]*)"\s*:', text_line)
        if match:
            return match.group(1)
    return None


def load_track_keys():
    try:
        tracks = json.loads(TRACKS.read_text(encoding="utf-8-sig"))["tracks"]
        if not isinstance(tracks, dict):
            raise TypeError("'tracks' is not an object")
        return list(tracks)
    except (OSError, ValueError, KeyError, TypeError) as err:
        print(f"Cannot read {TRACKS.relative_to(ROOT)}: {err}")
        return None


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_RECORDS
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as err:
        print(f"Cannot read {path}: {err}")
        return 1
    try:
        tracker = DuplicateTracker()
        data = json.loads(text, object_pairs_hook=tracker)
    except json.JSONDecodeError as err:
        print(f"{path} line {err.lineno}, column {err.colno}: {err.msg}")
        key = nearest_key(text, err.lineno)
        if key:
            print(f"Nearest track above: {key}")
        return 1
    track_keys = load_track_keys()
    if track_keys is None:
        return 1
    problems, warnings, tracks, records = check_data(data, track_keys, tracker.duplicates)
    for warning in warnings:
        print(f"warning: {warning}")
    for problem in problems:
        print(problem)
    if problems:
        print(f"{len(problems)} problem(s)")
        return 1
    print(f"OK: {tracks} tracks, {records} records")
    return 0


if __name__ == "__main__":
    sys.exit(main())
