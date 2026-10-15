import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import best_laps as bl
import log_best_laps as lbl
import records_file as rf
from check_track_records import check_record
from test_log_best_laps import make_log
from test_records_file import REC, TempFileCase

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

INDI = "Indianapolis Motor Speedway"
FORMULA = "Formula Americas 2020 Oval"
ID_MAP = {
    "tracks": {"indi": {"name": INDI, "layouts": {"": INDI}}},
    "cars": {"car_a": "Car A", "car_b": "Car B", "car_x": "Car X"},
}
CATALOG_TRACKS = {f"{INDI}::{INDI}"}
CATALOG_CARS = {"Car A", "Car B"}


def lap(ms, track="indi", layout="", car="car_a", driver="Pod 1", date="2026-01-01"):
    return (track, layout, car, driver, ms, date)


def rows_for(laps, id_map=ID_MAP, tracks=CATALOG_TRACKS, cars=CATALOG_CARS):
    return bl.best_laps(laps, id_map, tracks, cars)


def row(ms, car="Car A", matched=True, raw="indi /  / car_a"):
    return bl.BestLap(INDI, INDI, car, "Pod 1", ms, raw, matched)


def record(car, time, driver="Pod 9"):
    return {"class": "", "car": car, "driver": driver, "time": time, "source": ""}


def records_data(*records):
    return {INDI: {INDI: {"records": list(records)}}}


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.logs = Path(self.tmp.name) / "logs"
        shutil.copytree(HERE / "sample_logs", self.logs)
        self.cache = {}

    def test_scan_reads_valid_laps_only(self):
        laps, read, unreadable = bl.scan(self.logs, self.cache)
        self.assertEqual(read, 3)
        self.assertEqual(unreadable, [])
        times = sorted(item[4] for item in laps)
        self.assertEqual(len(laps), 9)
        self.assertNotIn(70000, times)
        self.assertIn(43019, times)

    def test_laps_carry_the_log_files_modified_date(self):
        stamp = datetime(2026, 3, 4, 12, 0).timestamp()
        os.utime(self.logs / "cut_lap.log", (stamp, stamp))
        laps, _, _ = bl.scan(self.logs, self.cache)
        self.assertIn("2026-03-04", {item[5] for item in laps})

    def test_second_scan_does_not_parse_again(self):
        bl.scan(self.logs, self.cache)
        with mock.patch.object(lbl, "parse_log", wraps=lbl.parse_log) as parse:
            laps, read, _ = bl.scan(self.logs, self.cache)
        self.assertEqual(parse.call_count, 0)
        self.assertEqual(read, 0)
        self.assertEqual(len(laps), 9)

    def test_appended_faster_lap_is_seen_next_scan(self):
        bl.scan(self.logs, self.cache)
        with open(self.logs / "two_sessions.log", "a", encoding="utf-8") as handle:
            handle.write("LAP Pod 5 0:40:000\nResult.OnLapCompleted. Cuts: 0\n")
        with mock.patch.object(lbl, "parse_log", wraps=lbl.parse_log) as parse:
            laps, read, _ = bl.scan(self.logs, self.cache)
        self.assertEqual(parse.call_count, 1)
        self.assertEqual(read, 1)
        self.assertIn(40000, [item[4] for item in laps])

    def test_deleted_log_drops_its_laps(self):
        bl.scan(self.logs, self.cache)
        (self.logs / "cut_lap.log").unlink()
        laps, _, _ = bl.scan(self.logs, self.cache)
        self.assertEqual(len(laps), 6)
        self.assertNotIn("cut_lap.log", self.cache)

    def test_log_that_fails_to_read_keeps_its_rows(self):
        first, _, _ = bl.scan(self.logs, self.cache)
        (self.logs / "cut_lap.log").write_text("changed", encoding="utf-8")
        with mock.patch.object(lbl, "parse_log", side_effect=ValueError("boom")):
            laps, _, unreadable = bl.scan(self.logs, self.cache)
        self.assertEqual(sorted(laps), sorted(first))
        self.assertEqual([name for name, _ in unreadable], ["cut_lap.log"])
        self.assertIn("cut_lap.log", self.cache)

    def test_missing_folder(self):
        with self.assertRaises(bl.LogsFolderError) as caught:
            bl.scan(self.logs / "nope", self.cache)
        self.assertEqual(str(caught.exception), "not found")
        self.assertEqual(caught.exception.kind, "not_found")

    def test_scandir_permission_error_is_unreachable(self):
        with mock.patch.object(bl.os, "scandir", side_effect=PermissionError("denied")):
            with self.assertRaises(bl.LogsFolderError) as caught:
                bl.scan(self.logs, self.cache)
        self.assertEqual(str(caught.exception), "(PermissionError)")
        self.assertEqual(caught.exception.kind, "unreachable")

    def test_empty_listing_with_failing_probe_is_an_error(self):
        probes = []

        def probe(path):
            probes.append(path)
            if len(probes) > 1:
                raise bl.LogsFolderError("unreachable", "(OSError)")

        with mock.patch.object(bl, "_probe", probe):
            with mock.patch.object(lbl, "read_changed_logs", return_value=({}, {}, [])):
                with self.assertRaises(bl.LogsFolderError):
                    bl.scan(self.logs, self.cache)
        self.assertEqual(len(probes), 2)

    def test_spectator_lap_is_excluded(self):
        (self.logs / "spec.log").write_text(
            make_log(pods=("Spectator",), laps=[("Spectator", "0:30:000", 0)]), encoding="utf-8")
        laps, _, _ = bl.scan(self.logs, self.cache)
        self.assertNotIn(30000, [item[4] for item in laps])


class RealDataTests(unittest.TestCase):
    def test_two_sessions_matches_the_catalog(self):
        records_path = ROOT / "db" / "userSetRecords.json"
        id_map = bl.load_editor_id_map(records_path)
        tracks = rf.load_catalog_tracks(records_path)
        cars = set(json.loads((ROOT / "data" / "cars.json").read_text(encoding="utf-8-sig"))["cars"])
        laps = [item + ("2026-01-01",) for item in
                lbl.parse_log((HERE / "sample_logs" / "two_sessions.log").read_text(encoding="utf-8"))]
        best = bl.best_laps(laps, id_map, tracks, cars)[0]
        self.assertEqual((best.track, best.layout, best.car), (INDI, INDI, FORMULA))
        self.assertEqual((best.driver, best.ms, best.matched), ("Pod 5", 43019, True))

    def test_id_map_names_exist_in_the_catalog(self):
        id_map = lbl.load_id_map(HERE / "ac_id_map.json")
        cars = json.loads((ROOT / "data" / "cars.json").read_text(encoding="utf-8-sig"))["cars"]
        tracks = json.loads((ROOT / "data" / "tracks.json").read_text(encoding="utf-8-sig"))["tracks"]
        for name in id_map["cars"].values():
            self.assertIn(name, cars)
        for track in id_map["tracks"].values():
            for layout in track["layouts"].values():
                self.assertIn(f"{track['name']}::{layout}", tracks)

    def test_catalog_and_id_map_loaders_fail_soft(self):
        missing = Path(tempfile.gettempdir()) / "no_such_repo" / "db" / "userSetRecords.json"
        self.assertEqual(rf.load_catalog_tracks(missing), set())
        self.assertIsNone(bl.load_editor_id_map(missing))

    def test_id_map_with_the_wrong_shape_is_ignored(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        (root / "tools").mkdir()
        records_path = root / "db" / "userSetRecords.json"
        shapes = ["[]", '{"tracks": []}', '{"tracks": {"a": 1}}', '{"tracks": {"a": {"layouts": []}}}',
                  '{"cars": []}', "not json", '{"tracks": {"t": {"name": 5}}, "cars": {}}',
                  '{"tracks": {}, "cars": {"c": ["x"]}}',
                  '{"tracks": {"t": {"layouts": {"L": {}}}}, "cars": {}}']
        for text in shapes:
            with self.subTest(text):
                (root / "tools" / "ac_id_map.json").write_text(text, encoding="utf-8")
                self.assertIsNone(bl.load_editor_id_map(records_path))


class BestLapsTests(unittest.TestCase):
    def test_matched_row_has_names_and_raw_ids(self):
        [best] = rows_for([lap(60000)])
        self.assertEqual((best.track, best.layout, best.car), (INDI, INDI, "Car A"))
        self.assertEqual(best.raw, "indi /  / car_a")
        self.assertTrue(best.matched)

    def test_unmatched_cases(self):
        cases = {
            "track": (lap(60000, track="other"), "other /  / car_a"),
            "layout": (lap(60000, layout="gp"), "indi / gp / car_a"),
            "car": (lap(60000, car="car_z"), "indi /  / car_z"),
            "car not in catalog": (lap(60000, car="car_x"), "indi /  / car_x"),
        }
        for label, (item, raw) in cases.items():
            with self.subTest(label):
                [best] = rows_for([item])
                self.assertFalse(best.matched)
                self.assertEqual(best.raw, raw)
                self.assertEqual(bl.marker(best, {}), f"unmatched: {raw}")

    def test_track_layout_not_in_catalog_is_unmatched(self):
        [best] = rows_for([lap(60000)], tracks=set())
        self.assertFalse(best.matched)
        self.assertTrue(bl.marker(best, {}).startswith("unmatched: indi"))

    def test_fastest_laps_per_car_are_listed_fastest_first(self):
        rows = rows_for([lap(60000), lap(59000, driver="Pod 2"), lap(61000, car="car_b")])
        self.assertEqual([(r.car, r.ms, r.driver) for r in rows],
                         [("Car A", 59000, "Pod 2"), ("Car A", 60000, "Pod 1"), ("Car B", 61000, "Pod 1")])

    def test_only_the_three_fastest_laps_per_car_are_kept(self):
        rows = rows_for([lap(64000), lap(61000), lap(63000), lap(62000), lap(60000, car="car_b")])
        self.assertEqual([(r.car, r.ms) for r in rows],
                         [("Car B", 60000), ("Car A", 61000), ("Car A", 62000), ("Car A", 63000)])

    def test_identical_times_count_once_and_keep_the_earlier_lap(self):
        rows = rows_for([lap(60000, driver="Pod 1"), lap(60000, driver="Pod 2"), lap(61000)])
        self.assertEqual([(r.ms, r.driver) for r in rows], [(60000, "Pod 1"), (61000, "Pod 1")])

    def test_each_row_keeps_its_own_date_and_driver(self):
        rows = rows_for([lap(60000, date="2026-01-01"), lap(59000, driver="Pod 2", date="2026-02-02"),
                         lap(59000, date="2026-03-03")])
        self.assertEqual([(r.ms, r.driver, r.date) for r in rows],
                         [(59000, "Pod 2", "2026-02-02"), (60000, "Pod 1", "2026-01-01")])

    def test_tie_keeps_first_lap(self):
        [best] = rows_for([lap(60000, driver="Pod 1"), lap(60000, driver="Pod 2")])
        self.assertEqual(best.driver, "Pod 1")

    def test_sort_puts_matched_first_then_track_layout_time(self):
        id_map = {
            "tracks": {"indi": {"name": INDI, "layouts": {"": INDI}},
                       "abc": {"name": "abc track", "layouts": {"": "Main", "b": "Zed"}}},
            "cars": ID_MAP["cars"],
        }
        tracks = {f"{INDI}::{INDI}", "abc track::Main", "abc track::Zed"}
        rows = rows_for([lap(50000, track="other"), lap(70000), lap(65000, car="car_b"),
                         lap(90000, track="abc", layout="b"), lap(95000, track="abc")],
                        id_map=id_map, tracks=tracks)
        self.assertEqual([(r.track, r.layout, r.ms, r.matched) for r in rows], [
            ("abc track", "Main", 95000, True),
            ("abc track", "Zed", 90000, True),
            (INDI, INDI, 65000, True),
            (INDI, INDI, 70000, True),
            ("other", "other", 50000, False),
        ])


class HandledTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.dict(os.environ, {"APPDATA": tmp.name})
        patch.start()
        self.addCleanup(patch.stop)

    def test_round_trip(self):
        handled = [(INDI, INDI, "Car A", 80000), ("T", "L", "Car B", 1)]
        bl.write_handled(handled)
        self.assertEqual(bl.read_handled(), handled)
        self.assertEqual(bl.handled_path().name, "best_laps_handled.json")

    def test_missing_or_bad_files_read_as_empty(self):
        self.assertEqual(bl.read_handled(), [])
        bl.handled_path().parent.mkdir(parents=True)
        for text in ("not json", "[]", '{"handled": 5}', '{"other": []}'):
            with self.subTest(text):
                bl.handled_path().write_text(text, encoding="utf-8")
                self.assertEqual(bl.read_handled(), [])

    def test_bad_entries_are_skipped(self):
        good = {"track": "T", "layout": "L", "car": "C", "ms": 5}
        bad = [5, {**good, "track": 1}, {**good, "layout": None}, {**good, "car": 2},
               {**good, "ms": True}, {**good, "ms": 5.5}, {**good, "ms": "5"}, {"track": "T"}]
        bl.handled_path().parent.mkdir(parents=True)
        bl.handled_path().write_text(json.dumps({"handled": bad + [good]}), encoding="utf-8")
        self.assertEqual(bl.read_handled(), [("T", "L", "C", 5)])

    def test_is_handled_matches_the_exact_lap_only(self):
        handled = [(INDI, INDI, "Car A", 80000)]
        self.assertTrue(bl.is_handled(row(80000), handled))
        self.assertFalse(bl.is_handled(row(81000), handled))
        self.assertFalse(bl.is_handled(row(79999), handled))
        self.assertFalse(bl.is_handled(row(80000, car="Car B"), handled))
        self.assertFalse(bl.is_handled(row(80000), []))


class LapRecordTests(unittest.TestCase):
    def test_fields_order_and_source(self):
        rec = bl.lap_record(row(80940), "Ann", "GT", "2026-05-06")
        self.assertEqual(list(rec.items()), [
            ("class", "GT"), ("car", "Car A"), ("driver", "Ann"), ("time", "1:20.940"),
            ("date", "2026-05-06"), ("source", "ac-server-log")])
        self.assertNotIn("year", rec)

    def test_empty_date_is_left_out(self):
        self.assertNotIn("date", bl.lap_record(row(80940), "Ann", "GT", ""))

    def test_no_class_is_refused(self):
        with self.assertRaises(rf.RecordsFileError) as caught:
            bl.lap_record(row(80940), "Ann", "", "2026-05-06")
        self.assertEqual(str(caught.exception), "Choose a class.")

    def test_bad_date_is_refused(self):
        with self.assertRaises(rf.RecordsFileError):
            bl.lap_record(row(80940), "Ann", "GT", "yesterday")


class AddLapTests(TempFileCase):
    def data(self):
        slower = dict(REC, car="Car A", time="1:30.000")
        blank = {"class": "", "car": "", "driver": "", "time": ""}
        return {"Track A": {"Layout 1": {"records": [slower, blank]}}}

    def add_lap(self, data):
        rf.add(data, "Track A", "Layout 1", bl.lap_record(row(80940), "Ann", "GT", "2026-05-06"))

    def test_lap_is_added_before_the_blank_and_old_record_is_untouched(self):
        for eol, bom in (("\r\n", False), ("\n", True), ("\r\n", True)):
            with self.subTest(eol=eol, bom=bom):
                self.write(self.data(), eol=eol, bom=bom)
                loaded = rf.save(self.path, self.add_lap)
                after = self.path.read_bytes()
                self.assertEqual(after.startswith(rf.BOM), bom)
                self.assertEqual(b"\r\n" in after, eol == "\r\n")
                old = rf.format_record(self.data()["Track A"]["Layout 1"]["records"][0])
                self.assertIn(old.replace("\n", eol).encode("utf-8"), after)
                records = loaded.data["Track A"]["Layout 1"]["records"]
                self.assertEqual([r["time"] for r in records], ["1:30.000", "1:20.940", ""])
                self.assertEqual(records[1]["source"], "ac-server-log")
                rf.parse_text(after.decode("utf-8-sig"))
                problems = []
                for rec in records[:2]:
                    check_record(rec, "record", problems, {})
                self.assertEqual(problems, [])

    def test_other_edit_on_disk_after_load_is_kept(self):
        self.write(self.data())
        rf.load(self.path)
        other = self.data()
        other["Track B"] = {"Full": {"records": [{"class": "", "car": "", "driver": "", "time": ""}]}}
        self.write(other)
        loaded = rf.save(self.path, self.add_lap)
        self.assertIn("Track B", loaded.data)
        self.assertEqual(len(loaded.data["Track A"]["Layout 1"]["records"]), 3)

    def test_layout_removed_on_disk_conflicts_and_changes_nothing(self):
        self.write({"Track A": {"Other": {"records": []}}})
        before = self.path.read_bytes()
        with self.assertRaises(rf.ConflictError):
            rf.save(self.path, lambda d: [self.add_lap(d), rf.add(d, "Track A", "Layout 1", dict(REC))])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), [self.path.name])


class MarkerTests(unittest.TestCase):
    def test_beats_ties_trails(self):
        data = records_data(record("Car A", "1:20.940"))
        self.assertEqual(bl.marker(row(80000), data), "beats current record")
        self.assertEqual(bl.marker(row(80940), data), "ties")
        self.assertEqual(bl.marker(row(81000), data), "trails")

    def test_equal_time_written_with_short_fraction_ties(self):
        self.assertEqual(bl.marker(row(80940), records_data(record("Car A", "1:20.94"))), "ties")

    def test_no_record(self):
        blank = {"class": "", "car": "", "driver": "", "time": ""}
        cases = {
            "layout absent": {},
            "different car only": records_data(record("Car B", "1:00.000")),
            "blank records only": records_data(blank),
        }
        for label, data in cases.items():
            with self.subTest(label):
                self.assertEqual(bl.marker(row(80000), data), "no record")

    def test_fastest_of_several_records_is_used(self):
        data = records_data(record("Car A", "1:30.000"), record("Car A", "1:10.000"),
                            record("Car A", "1:20.000"))
        self.assertEqual(bl.marker(row(75000), data), "trails")
        self.assertEqual(bl.marker(row(70000), data), "ties")

    def test_unusable_record_times_are_ignored(self):
        data = records_data(record("Car A", "1:20.9400"), record("Car A", "fast"))
        self.assertEqual(bl.marker(row(80000), data), "no record")


class StatusMessageTests(unittest.TestCase):
    def test_error_messages(self):
        self.assertEqual(bl.error_message("D:/logs", "not_found", "not found"),
                         "Best laps: logs folder not found: D:/logs. Retrying every 10 min.")
        self.assertEqual(bl.error_message("D:/logs", "unreachable", "(PermissionError)"),
                         "Best laps: cannot read logs folder D:/logs (PermissionError). Retrying every 10 min.")
        self.assertEqual(bl.error_message("D:/logs", "failed", "scan failed (ValueError)"),
                         "Best laps: scan failed (ValueError). Retrying every 10 min.")

    def test_ok_messages(self):
        checked = datetime(2026, 1, 1, 14, 5, 9)
        self.assertEqual(bl.ok_message(checked, 3, 0, [], True),
                         "Best laps: 3 readable logs, 0 re-read, checked at 14:05:09 (next check about 14:15)")
        self.assertEqual(bl.ok_message(checked, 3, 2, [("a.log", "OSError")], False),
                         "Best laps: 3 readable logs, 2 re-read, checked at 14:05:09 (next check about 14:15), "
                         "1 unreadable, id map missing or unusable: all laps unmatched")


if __name__ == "__main__":
    unittest.main()
