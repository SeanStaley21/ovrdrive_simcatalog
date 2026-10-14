"""Read, edit and safely save db/userSetRecords.json for the Records Editor."""
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from check_track_records import (
    DuplicateTracker,
    reject_constant,
    NonStandardNumber,
    check_record,
    is_blank,
)

BOM = b"\xef\xbb\xbf"
RETRY_DELAYS = (0.2, 0.4, 0.8, 1.6, 3.2)
LOCKED_MESSAGE = "File is locked by another program (OneDrive/VS Code?). Nothing was changed."
CONFLICT_MESSAGE = "This record was changed or removed in the file since it was loaded. Reload."


class RecordsFileError(Exception):
    pass


class ConflictError(RecordsFileError):
    pass


class SavedButUnreadableError(RecordsFileError):
    """The file was written, but reading it back afterwards failed."""


@dataclass
class Loaded:
    path: Path
    data: dict
    eol: str
    bom: bool
    final_newline: bool
    warnings: list = field(default_factory=list)
    reformats: bool = False


def blank_record():
    return {"class": "", "car": "", "driver": "", "time": ""}


def format_record(rec):
    fields = ", ".join(
        json.dumps(k, ensure_ascii=False) + ": " + json.dumps(v, ensure_ascii=False)
        for k, v in rec.items()
    )
    return "{ " + fields + " }"


def format_entry(entry):
    lines = []
    for key, value in entry.items():
        name = json.dumps(key, ensure_ascii=False)
        if key == "records":
            if not value:
                lines.append(f"      {name}: []")
            else:
                body = ",\n".join("        " + format_record(r) for r in value)
                lines.append(f"      {name}: [\n{body}\n      ]")
        else:
            lines.append(f"      {name}: {json.dumps(value, ensure_ascii=False)}")
    return ",\n".join(lines)


def format_text(data, eol, final_newline):
    if not data:
        text = "{}"
    else:
        tracks = []
        for track, layouts in data.items():
            head = "  " + json.dumps(track, ensure_ascii=False) + ": "
            if not layouts:
                tracks.append(head + "{}")
                continue
            parts = []
            for layout, entry in layouts.items():
                lhead = "    " + json.dumps(layout, ensure_ascii=False) + ": "
                if not entry:
                    parts.append(lhead + "{}")
                else:
                    parts.append(lhead + "{\n" + format_entry(entry) + "\n    }")
            tracks.append(head + "{\n" + ",\n".join(parts) + "\n  }")
        text = "{\n" + ",\n".join(tracks) + "\n}"
    if final_newline:
        text += "\n"
    return text.replace("\n", eol)


def _line_col(text, index):
    line = text.count("\n", 0, index) + 1
    column = index - (text.rfind("\n", 0, index) + 1) + 1
    return line, column


def _duplicate_problems(data, tracker):
    found = []
    named = set()

    def report(obj, where):
        named.add(id(obj))
        for key in tracker.duplicates.get(id(obj), []):
            found.append(f"{where}: duplicate key '{key}'")

    report(data, "Top level (track)")
    if isinstance(data, dict):
        for track, layouts in data.items():
            if not isinstance(layouts, dict):
                continue
            report(layouts, f"{track} (layout)")
            for layout, entry in layouts.items():
                if not isinstance(entry, dict):
                    continue
                report(entry, f"{track} / {layout} (entry field)")
                records = entry.get("records")
                if isinstance(records, list):
                    for n, rec in enumerate(records, 1):
                        if isinstance(rec, dict):
                            report(rec, f"{track} / {layout} record {n} (record field)")
    for obj_id, keys in tracker.duplicates.items():
        if obj_id not in named:
            for key in keys:
                found.append(f"Nested object: duplicate key '{key}'")
    return found


def _shape_problems(data):
    if not isinstance(data, dict):
        return ["Top level must be an object keyed by track name."]
    problems = []
    for track, layouts in data.items():
        if "::" in track:
            problems.append(f"{track}: track name must not contain '::'")
        if not isinstance(layouts, dict):
            problems.append(f"{track}: must be an object of layouts")
            continue
        for layout, entry in layouts.items():
            where = f"{track} / {layout}"
            if "::" in layout:
                problems.append(f"{where}: layout name must not contain '::'")
            if not isinstance(entry, dict):
                problems.append(f"{where}: must be an object with a 'records' list")
                continue
            records = entry.get("records")
            if not isinstance(records, list):
                problems.append(f"{where}: 'records' is missing or not a list")
                continue
            for n, rec in enumerate(records, 1):
                if not isinstance(rec, dict):
                    problems.append(f"{where} record {n}: record is not an object")
    return problems


def parse_text(text):
    tracker = DuplicateTracker()
    try:
        data = json.loads(text, object_pairs_hook=tracker, parse_constant=reject_constant)
    except NonStandardNumber as err:
        match = re.search(r"[:\[,]\s*(" + re.escape(str(err)) + r")", text)
        line, column = _line_col(text, match.start(1) if match else 0)
        raise RecordsFileError(f"Line {line}, column {column}: {err} is not valid JSON.") from None
    except json.JSONDecodeError as err:
        raise RecordsFileError(f"Line {err.lineno}, column {err.colno}: {err.msg}.") from None
    problems = _duplicate_problems(data, tracker) + _shape_problems(data)
    if problems:
        raise RecordsFileError("The file cannot be edited:\n" + "\n".join(problems))
    return data


def _decode(raw):
    bom = raw.startswith(BOM)
    try:
        text = (raw[len(BOM):] if bom else raw).decode("utf-8")
    except UnicodeDecodeError as err:
        raise RecordsFileError(f"The file is not valid UTF-8: {err}") from None
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    eol = "\r\n" if crlf > lf else "\n"
    return text, bom, eol, text.endswith("\n"), crlf > 0 and lf > 0


def _read(path):
    try:
        raw = Path(path).read_bytes()
    except OSError as err:
        raise RecordsFileError(f"Cannot read {path}: {err}") from None
    text, bom, eol, final_newline, mixed = _decode(raw)
    return text, parse_text(text), bom, eol, final_newline, mixed


def load(path):
    text, data, bom, eol, final_newline, mixed = _read(path)
    warnings = []
    if mixed:
        warnings.append("The file mixes CRLF and LF line endings; saving will use one style throughout.")
    for track, layouts in data.items():
        for layout, entry in layouts.items():
            for n, rec in enumerate(entry["records"], 1):
                if not is_blank(rec):
                    check_record(rec, f"{track} / {layout} record {n}", warnings, {})
    expected = format_text(data, eol, final_newline)
    reformats = expected != text
    if reformats:
        old_lines = text.split("\n")
        new_lines = expected.split("\n")
        line = next(
            (i for i, (a, b) in enumerate(zip(old_lines, new_lines), 1) if a != b),
            min(len(old_lines), len(new_lines)) + 1,
        )
        warnings.append(f"Saving will reformat the file; first difference at line {line}.")
    return Loaded(Path(path), data, eol, bom, final_newline, warnings, reformats)


def build_record(cls, car, driver, time, year_text, base=None):
    rec = dict(base) if base is not None else {}
    for key, value in (("class", cls), ("car", car), ("driver", driver), ("time", time)):
        rec[key] = value.strip()
    year_text = year_text.strip()
    if not year_text:
        rec.pop("year", None)
    else:
        top = date.today().year + 1
        if not re.fullmatch(r"[0-9]+", year_text) or not 1900 <= int(year_text) <= top:
            raise RecordsFileError(f"Year must be a whole number from 1900 to {top}, or left empty.")
        rec["year"] = int(year_text)
    problems = []
    check_record(rec, "record", problems, {})
    if problems:
        raise RecordsFileError("\n".join(problems))
    return rec


def _layout(data, track, layout):
    layouts = data.get(track)
    entry = layouts.get(layout) if layouts is not None else None
    if entry is None:
        raise ConflictError(f"{track} / {layout} is no longer in the file. Reload.")
    return entry


def _normalize(entry, records):
    entry["records"] = [r for r in records if not is_blank(r)] + [blank_record()]


def _index_of(entry, original):
    for index, rec in enumerate(entry["records"]):
        if rec == original:
            return index
    raise ConflictError(CONFLICT_MESSAGE)


def add(data, track, layout, rec):
    entry = _layout(data, track, layout)
    _normalize(entry, entry["records"] + [rec])


def replace(data, track, layout, original, new):
    entry = _layout(data, track, layout)
    records = list(entry["records"])
    records[_index_of(entry, original)] = new
    _normalize(entry, records)


def delete(data, track, layout, original):
    entry = _layout(data, track, layout)
    records = list(entry["records"])
    del records[_index_of(entry, original)]
    _normalize(entry, records)


def _replace_with_retry(tmp, path):
    for delay in (*RETRY_DELAYS, None):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if delay is None:
                raise RecordsFileError(LOCKED_MESSAGE) from None
            time.sleep(delay)


def save(path, apply):
    _, data, bom, eol, final_newline, _ = _read(path)
    apply(data)
    try:
        intended = format_text(data, eol, final_newline).encode("utf-8")
    except UnicodeEncodeError:
        raise RecordsFileError(
            "The file contains text that cannot be saved as UTF-8 (a lone surrogate). Nothing was changed."
        ) from None
    if bom:
        intended = BOM + intended
    tmp = f"{path}.records-editor.tmp"
    try:
        with open(tmp, "wb") as handle:
            handle.write(intended)
            handle.flush()
            os.fsync(handle.fileno())
        with open(tmp, "rb") as handle:
            written = handle.read()
        if written != intended:
            raise RecordsFileError("The temporary file did not match what was written. Nothing was changed.")
        parse_text(_decode(written)[0])
        _replace_with_retry(tmp, path)
    except OSError as err:
        raise RecordsFileError(f"Could not write the file: {err}. Nothing was changed.") from None
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    try:
        return load(path)
    except RecordsFileError as err:
        raise SavedButUnreadableError(
            f"The file WAS saved, but reading it back failed: {err}"
        ) from None


def load_catalog_cars(records_path):
    try:
        cars_file = Path(records_path).parent.parent / "data" / "cars.json"
        return set(json.loads(cars_file.read_text(encoding="utf-8-sig"))["cars"])
    except Exception:
        return set()


def load_cars(records_path, data):
    names = load_catalog_cars(records_path)
    for layouts in data.values():
        for entry in layouts.values():
            for rec in entry["records"]:
                if not is_blank(rec) and isinstance(rec.get("car"), str):
                    names.add(rec["car"])
    return sorted(names, key=str.casefold)


def filter_cars(cars, text):
    """Cars whose name contains text (case-insensitive), names starting with it first."""
    needle = text.strip().casefold()
    if not needle:
        return list(cars)
    hits = [car for car in cars if needle in car.casefold()]
    return sorted(hits, key=lambda car: (not car.casefold().startswith(needle), car.casefold()))


def config_path():
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home()
    return root / "OVRDrive Records Editor" / "config.json"


def read_saved_path():
    try:
        value = json.loads(config_path().read_text(encoding="utf-8"))["records_path"]
        return value if isinstance(value, str) and value else None
    except Exception:
        return None


def write_saved_path(path):
    target = config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"records_path": str(path)}), encoding="utf-8")
