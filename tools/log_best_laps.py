"""Keep the best lap per track, layout and car from Assetto Corsa server logs.

Usage:
  python tools/log_best_laps.py --logs-dir "C:\\...\\Server Logs"          watch, rescan every 30 s
  python tools/log_best_laps.py --logs-dir DIR --once                      one pass, then exit

Options:
  --logs-dir DIR    folder holding the "AC LAN Main Server_*.log" files (required)
  --out FILE        records file to maintain (default: bestLapsTest.json next to the tool)
  --map FILE        id map (default: ac_id_map.json next to the tool)
  --interval SEC    seconds between scans (default 30)
  --once            scan once and exit

The output has the nesting of db/userSetRecords.json
({"Track": {"Layout": {"records": [...]}}}) and can be checked with
python tools/check_track_records.py --nested FILE. A sidecar FILE.state.json remembers which
logs were already read; deleting it is always safe.
"""
import argparse
import copy
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

SOURCE = "ac-server-log"
SPECTATOR = "Spectator"
DEFAULT_INTERVAL = 30
REPLACE_ATTEMPTS = 8
REPLACE_DELAY = 0.5

TRACK_RE = re.compile(r"^TRACK=(.*)$")
CARS_RE = re.compile(r"^CARS=(.*)$")
LAYOUT_RE = re.compile(r"^Initializing checksum for track config (.*)$")
POD_RE = re.compile(r"^CAR: \d+ (\S+) \(\d+\) \[(.*) \[\d*\]\]")
LAP_RE = re.compile(r"^LAP (.+) (\d+):(\d{2}):(\d{3})$")
CUTS_RE = re.compile(r"^Result\.OnLapCompleted\. Cuts: (\d+)\s*$")
TIME_RE = re.compile(r"^(\d+):(\d{2})\.(\d{1,3})$")

log = logging.getLogger("log_best_laps")


class OutputError(Exception):
    pass


def base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def format_time(ms):
    minutes, rest = divmod(ms, 60000)
    return f"{minutes}:{rest // 1000:02d}.{rest % 1000:03d}"


def parse_time(text):
    match = TIME_RE.match(text) if isinstance(text, str) else None
    if not match:
        return None
    minutes, seconds, fraction = match.groups()
    return (int(minutes) * 60 + int(seconds)) * 1000 + int(fraction.ljust(3, "0"))


def parse_log(text):
    """Return (track_id, layout_id, car_id, driver, ms) for every valid lap in one log.

    A lap is valid when its LAP line is followed by a Result.OnLapCompleted line with
    Cuts: 0, the driver is not the Spectator slot and the log names a track and a car.
    """
    track_id = None
    cars = None
    layout_id = None
    car_by_driver = {}
    raw_laps = []
    pending = None
    for line in text.splitlines():
        if line.startswith("TRACK=") and track_id is None:
            track_id = TRACK_RE.match(line).group(1).strip().replace("\\", "/").rsplit("/", 1)[-1]
        elif line.startswith("CARS=") and cars is None:
            try:
                parsed = json.loads(CARS_RE.match(line).group(1))
            except ValueError:
                parsed = None
            if isinstance(parsed, list):
                cars = [c for c in parsed if isinstance(c, str)]
        elif line.startswith("Initializing checksum for track config ") and layout_id is None:
            layout_id = LAYOUT_RE.match(line).group(1).strip()
        elif line.startswith("CAR: "):
            match = POD_RE.match(line)
            if match:
                car_by_driver[match.group(2)] = match.group(1)
        elif line.startswith("LAP "):
            match = LAP_RE.match(line)
            pending = None
            if match:
                name, minutes, seconds, millis = match.groups()
                pending = (name, (int(minutes) * 60 + int(seconds)) * 1000 + int(millis))
        elif line.startswith("Result.OnLapCompleted"):
            match = CUTS_RE.match(line)
            if pending and match and int(match.group(1)) == 0:
                raw_laps.append(pending)
            pending = None
    if not track_id or not cars:
        return []
    laps = []
    for driver, ms in raw_laps:
        car_id = car_by_driver.get(driver, cars[0])
        if driver != SPECTATOR and ms > 0:
            laps.append((track_id, layout_id or "", car_id, driver, ms))
    return laps


def load_id_map(path):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return {"tracks": data.get("tracks", {}), "cars": data.get("cars", {})}


def resolve_names(id_map, track_id, layout_id, car_id, unmapped):
    """Return display names (track, layout, car), noting every id that had no entry."""
    track = id_map["tracks"].get(track_id)
    if track is None:
        unmapped.add(f"track {track_id}")
        track_name = track_id
        layout_name = layout_id or track_id
    else:
        track_name = track.get("name", track_id)
        layout_name = track.get("layouts", {}).get(layout_id)
        if layout_name is None:
            unmapped.add(f"layout {track_id}/{layout_id or '(none)'}")
            layout_name = layout_id or track_name
    car_name = id_map["cars"].get(car_id)
    if car_name is None:
        unmapped.add(f"car {car_id}")
        car_name = car_id
    return track_name, layout_name, car_name


def load_records(path):
    """Read the existing records file; an absent file gives an empty set of records."""
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise OutputError(f"cannot read {path.name}: {type(exc).__name__}") from exc
    ok = isinstance(data, dict) and all(
        isinstance(layouts, dict)
        and all(isinstance(entry, dict) and isinstance(entry.get("records", []), list)
                for entry in layouts.values())
        for layouts in data.values()
    )
    if not ok:
        raise OutputError(f"{path.name} is not shaped like db/userSetRecords.json")
    return data


def merge_lap(data, track_name, layout_name, car_name, driver, ms):
    """Store the lap if it beats the stored record for that car. Returns True on change."""
    entry = data.setdefault(track_name, {}).setdefault(layout_name, {})
    records = entry.setdefault("records", [])
    for record in records:
        if isinstance(record, dict) and record.get("car") == car_name:
            stored = parse_time(record.get("time"))
            if stored is not None and stored <= ms:
                return False
            record["time"] = format_time(ms)
            record["driver"] = driver
            record["source"] = SOURCE
            return True
    records.append({"class": "", "car": car_name, "driver": driver,
                    "time": format_time(ms), "source": SOURCE})
    return True


def sort_records(data):
    def lap_key(record):
        ms = parse_time(record.get("time")) if isinstance(record, dict) else None
        return (ms is None, ms or 0)

    out = {}
    for track in sorted(data):
        out[track] = {}
        for layout in sorted(data[track]):
            entry = dict(data[track][layout])
            entry["records"] = sorted(entry.get("records", []), key=lap_key)
            out[track][layout] = entry
    return out


def atomic_write(path, text):
    """Write text to path through a temp file so a reader never sees a partial file."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(REPLACE_ATTEMPTS):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == REPLACE_ATTEMPTS - 1:
                    raise
                time.sleep(REPLACE_DELAY)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def write_json(path, data):
    atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def load_state(path):
    try:
        with open(path, encoding="utf-8") as handle:
            files = json.load(handle).get("files", {})
    except (OSError, ValueError, AttributeError):
        return {}
    return files if isinstance(files, dict) else {}


def file_signature(path):
    stat = path.stat()
    return [stat.st_size, stat.st_mtime_ns]


def run_pass(logs_dir, out_path, id_map, state, data, unmapped, reported):
    """Read every changed log, merge its laps into data, write if anything improved.

    Returns the updated data; the caller's data is left untouched if the write fails, so
    the next pass redoes the merge. state is updated in place once the write succeeded.
    """
    data = copy.deepcopy(data)
    changed = not out_path.exists()
    seen = {}
    for path in sorted(logs_dir.glob("*.log")):
        try:
            signature = file_signature(path)
            seen[path.name] = signature
            if state.get(path.name) == signature:
                continue
            text = path.read_bytes().decode("utf-8-sig", errors="replace")
            laps = parse_log(text)
        except Exception as exc:
            seen.pop(path.name, None)
            log.warning("cannot read %s: %s", path.name, type(exc).__name__)
            continue
        for track_id, layout_id, car_id, driver, ms in laps:
            names = resolve_names(id_map, track_id, layout_id, car_id, unmapped)
            if merge_lap(data, *names, driver, ms):
                changed = True
    if changed:
        data = sort_records(data)
        write_json(out_path, data)
        log.info("wrote %s", out_path.name)
    for item in sorted(unmapped - reported):
        log.warning("no id map entry for %s", item)
    reported |= unmapped
    state.update(seen)
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description="Maintain best laps from AC server logs.")
    parser.add_argument("--logs-dir", required=True)
    parser.add_argument("--out", default=str(base_dir() / "bestLapsTest.json"))
    parser.add_argument("--map", default=str(base_dir() / "ac_id_map.json"))
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logs_dir = Path(args.logs_dir)
    out_path = Path(args.out)
    state_path = out_path.with_name(out_path.name + ".state.json")
    if not logs_dir.is_dir():
        log.error("logs folder not found: %s", logs_dir)
        return 2
    try:
        id_map = load_id_map(Path(args.map))
        data = load_records(out_path)
    except (OSError, ValueError, OutputError) as exc:
        log.error("%s", exc if isinstance(exc, OutputError) else f"cannot load {type(exc).__name__}")
        return 2

    state = load_state(state_path) if out_path.exists() else {}
    unmapped = set()
    reported = set()
    try:
        while True:
            try:
                data = run_pass(logs_dir, out_path, id_map, state, data, unmapped, reported)
                write_json(state_path, {"files": state})
            except OSError as exc:
                log.warning("pass failed: %s", type(exc).__name__)
                if args.once:
                    return 1
            if args.once:
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
