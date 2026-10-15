"""Check the track record files for the mistakes hand editing causes.

Usage:
  python tools/check_track_records.py                 check db/track-records.json
                                                      (flat) and db/userSetRecords.json
                                                      (nested)
  python tools/check_track_records.py PATH            check one flat file
                                                      ({"Track::Layout": {...}})
  python tools/check_track_records.py --nested PATH   check one nested file
                                                      ({"Track": {"Layout": {...}}})
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RECORDS = ROOT / "db" / "track-records.json"
USER_SET_RECORDS = ROOT / "db" / "userSetRecords.json"
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
TIME_RE = re.compile(r"\d+:[0-5]\d\.\d{1,4}")
DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

REQUIRED = ["class", "car", "driver", "time"]
OPTIONAL = ["lap_type", "year", "date", "source", "confidence", "verified", "speed_mph", "note"]
ENTRY_FIELDS = ["records", "no_record_reason"]
NESTED_SKIP = set(ENTRY_FIELDS) | set(REQUIRED) | set(OPTIONAL)


class NonStandardNumber(ValueError):
    pass


def reject_constant(name):
    raise NonStandardNumber(name)


class DuplicateTracker:
    """object_pairs_hook that remembers which keys appeared twice in which object."""

    def __init__(self):
        self.duplicates = {}
        self.objects = []

    def __call__(self, pairs):
        obj = {}
        self.objects.append(obj)
        for key, value in pairs:
            if key in obj:
                self.duplicates.setdefault(id(obj), []).append(key)
            obj[key] = value
        return obj


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_blank(rec):
    """A template record: exactly the four required keys, each an empty string."""
    return (
        isinstance(rec, dict)
        and set(rec) == set(REQUIRED)
        and all(isinstance(v, str) and not v.strip() for v in rec.values())
    )


def sort_key(key):
    return tuple(part.casefold() for part in key.split("::"))


def is_real_date(value):
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


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
    if isinstance(time, str) and time.strip() and not TIME_RE.fullmatch(time):
        problems.append(f"{label}: time '{time}' must look like m:ss.mmm (e.g. 1:20.942)")
    for field, allowed in (("class", CLASSES), ("lap_type", LAP_TYPES), ("confidence", CONFIDENCES)):
        if field not in rec:
            continue
        if field == "class" and not (isinstance(rec[field], str) and rec[field].strip()):
            continue
        if rec[field] not in allowed:
            problems.append(f"{label}: {field} '{rec[field]}' is not allowed; use one of: {', '.join(allowed)}")
    if "verified" in rec and not isinstance(rec["verified"], bool):
        problems.append(f"{label}: 'verified' must be true or false")
    if "year" in rec and (not isinstance(rec["year"], int) or isinstance(rec["year"], bool)):
        problems.append(f"{label}: 'year' must be a whole number")
    if "date" in rec and not is_real_date(rec["date"]):
        problems.append(f"{label}: 'date' must be a real date written YYYY-MM-DD (e.g. 2026-10-12)")
    if "speed_mph" in rec and not is_number(rec["speed_mph"]):
        problems.append(f"{label}: 'speed_mph' must be a number")
    for field in ("source", "note"):
        if field in rec and not isinstance(rec[field], str):
            problems.append(f"{label}: '{field}' must be a string")


def flatten_nested(data, duplicates):
    """Turn {"Track": {"Layout": entry}} into {"Track::Layout": entry}.

    Returns (flat, problems, warnings, bad_tracks). The entries are the original
    objects, so the duplicate-key lookups by id keep working.
    """
    flat = {}
    problems = []
    warnings = []
    bad_tracks = set()
    if not isinstance(data, dict):
        problems.append("top level must be an object keyed by track name")
        return flat, problems, warnings, bad_tracks
    for track in duplicates.get(id(data), []):
        problems.append(f"{track}: duplicate track key")
    tracks = list(data)
    for prev, cur in zip(tracks, tracks[1:]):
        if prev.casefold() > cur.casefold():
            warnings.append(f"{cur}: out of order (should come before {prev})")
    for track, layouts in data.items():
        if "::" in track:
            problems.append(f"{track}: track name must not contain '::'")
            bad_tracks.add(track)
            continue
        if not isinstance(layouts, dict):
            problems.append(f'{track}: must be an object of layouts, like {{"Layout": {{"records": [...]}}}}')
            bad_tracks.add(track)
            continue
        for layout in duplicates.get(id(layouts), []):
            problems.append(f"{track} / {layout}: duplicate layout key")
        names = list(layouts)
        for prev, cur in zip(names, names[1:]):
            if prev.casefold() > cur.casefold():
                warnings.append(f"{track} / {cur}: out of order (should come before {prev})")
        for layout, entry in layouts.items():
            if "::" in layout:
                problems.append(f"{track} / {layout}: layout name must not contain '::'")
                continue
            flat[f"{track}::{layout}"] = entry
    return flat, problems, warnings, bad_tracks


def check_data(data, track_keys, duplicates, nested=False, bad_tracks=()):
    problems = []
    warnings = []
    records = 0
    if not isinstance(data, dict):
        return ["top level must be an object keyed by Track::Layout"], warnings, 0, 0
    if not nested:
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
            if is_blank(rec) and not duplicates.get(id(rec)):
                continue
            records += 1
            check_record(rec, f"{key} record {n}", problems, duplicates)
    for key in track_keys:
        if key in data:
            continue
        track, _, layout = key.partition("::")
        if not nested:
            problems.append(f'{key}: missing; add {{"records": []}}')
        elif track not in bad_tracks:
            problems.append(
                f'{track} / {layout}: missing; add "{layout}": {{"records": '
                f'[{{ "class": "", "car": "", "driver": "", "time": "" }}]}} under "{track}"'
            )
    if not nested:
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


def nearest_track_layout(text, line):
    layout = None
    for text_line in reversed(text.splitlines()[: max(line - 1, 0)]):
        if layout is None:
            match = re.match(r'^ {4}"([^"]+)"\s*:', text_line)
            if match and match.group(1) not in NESTED_SKIP:
                layout = match.group(1)
                continue
        match = re.match(r'^ {2}"([^"]+)"\s*:', text_line)
        if match and match.group(1) not in NESTED_SKIP:
            return f"{match.group(1)} / {layout}" if layout else match.group(1)
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


def print_location(text, line, nested):
    if nested:
        found = nearest_track_layout(text, line)
        if found:
            print(f"Nearest above: {found}")
    else:
        key = nearest_key(text, line)
        if key:
            print(f"Nearest track above: {key}")


def check_file(path, track_keys, nested):
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as err:
        print(f"Cannot read {path}: {err}")
        return 1
    try:
        tracker = DuplicateTracker()
        data = json.loads(text, object_pairs_hook=tracker, parse_constant=reject_constant)
    except NonStandardNumber as err:
        match = re.search(r"[:\[,]\s*(" + re.escape(str(err)) + r")", text)
        index = match.start(1) if match else 0
        line = text.count("\n", 0, index) + 1
        column = index - (text.rfind("\n", 0, index) + 1) + 1
        print(f"{path} line {line}, column {column}: {err} is not valid JSON")
        print_location(text, line, nested)
        return 1
    except json.JSONDecodeError as err:
        print(f"{path} line {err.lineno}, column {err.colno}: {err.msg}")
        print_location(text, err.lineno, nested)
        return 1
    if nested:
        flat, problems, warnings, bad_tracks = flatten_nested(data, tracker.duplicates)
        more_problems, more_warnings, layouts, records = check_data(
            flat, track_keys, tracker.duplicates, nested=True, bad_tracks=bad_tracks
        )
        problems += more_problems
        warnings += more_warnings
        summary = f"{len(data) if isinstance(data, dict) else 0} tracks, {layouts} layouts, {records} records"
    else:
        problems, warnings, tracks, records = check_data(data, track_keys, tracker.duplicates)
        summary = f"{tracks} tracks, {records} records"
    for warning in warnings:
        print(f"warning: {warning}")
    for problem in problems:
        print(problem)
    if problems:
        print(f"{len(problems)} problem(s)")
        return 1
    print(f"OK: {summary}")
    return 0


def main():
    sys.stdout.reconfigure(errors="backslashreplace")
    sys.stderr.reconfigure(errors="backslashreplace")
    args = sys.argv[1:]
    if not args:
        targets = [(DEFAULT_RECORDS, False), (USER_SET_RECORDS, True)]
    elif len(args) == 1 and args[0] != "--nested":
        targets = [(Path(args[0]), False)]
    elif len(args) == 2 and args[0] == "--nested":
        targets = [(Path(args[1]), True)]
    else:
        print("Usage: python tools/check_track_records.py [PATH | --nested PATH]")
        return 1
    track_keys = load_track_keys()
    if track_keys is None:
        return 1
    status = 0
    for path, nested in targets:
        if len(targets) > 1:
            print(f"{path.relative_to(ROOT).as_posix()}:")
        status |= check_file(path, track_keys, nested)
    return status


if __name__ == "__main__":
    sys.exit(main())
