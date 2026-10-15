import json
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import best_laps as bl
import log_best_laps as lbl
import records_file as rf
from test_log_best_laps import make_log

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


def lap(ms, track="indi", layout="", car="car_a", driver="Pod 1"):
    return (track, layout, car, driver, ms)


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
        laps = lbl.parse_log((HERE / "sample_logs" / "two_sessions.log").read_text(encoding="utf-8"))
        [best] = bl.best_laps(laps, id_map, tracks, cars)
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

    def test_fastest_lap_per_car_wins(self):
        rows = rows_for([lap(60000), lap(59000, driver="Pod 2"), lap(61000, car="car_b")])
        self.assertEqual([(r.car, r.ms, r.driver) for r in rows],
                         [("Car A", 59000, "Pod 2"), ("Car B", 61000, "Pod 1")])

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


class MarkerTests(unittest.TestCase):
    def test_beats_ties_trails(self):
        data = records_data(record("Car A", "1:20.940"))
        self.assertEqual(bl.marker(row(80000), data), "beats")
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
