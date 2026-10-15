import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import log_best_laps as lbl

HERE = Path(__file__).resolve().parent
SAMPLES = HERE / "sample_logs"

ID_MAP = {
    "tracks": {
        "indi": {"name": "Indianapolis Motor Speedway", "layouts": {"": "Indianapolis Motor Speedway"}},
        "daytona_2017": {"name": "Daytona International Speedway", "layouts": {"oval": "Nascar"}},
    },
    "cars": {"rss_formula_americas_2020_oval": "Formula Americas 2020 Oval"},
}


def sample(name):
    return (SAMPLES / name).read_text(encoding="utf-8")


def make_log(track="indi", cars='["car_a"]', layout=None, pods=("Pod 3",), laps=()):
    """Build a minimal log. laps is a list of (driver, 'm:ss:mmm', cuts)."""
    lines = [f"TRACK=csp/2000/../D/../{track}", f"CARS={cars}", "SESSION: Race", "TYPE=RACE"]
    if layout is not None:
        lines.append(f"Initializing checksum for track config {layout}")
    for number, pod in enumerate(pods):
        lines.append(f"CAR: {number} car_a ({number}) [{pod} [{number}]] {pod} [{number}] {number} Ballast: 0 kg")
    for driver, lap_time, cuts in laps:
        lines += ["Car.onLapCompleted", f"LAP {driver} {lap_time}", "SPLIT COUNT: 3",
                  "Dynamic track ok", f"Result.OnLapCompleted. Cuts: {cuts}", "SendLapCompletedMessage"]
    return "\n".join(lines) + "\n"


class ParseLogTests(unittest.TestCase):
    def test_two_session_log_collects_laps_from_both_sessions(self):
        laps = lbl.parse_log(sample("two_sessions.log"))
        self.assertEqual(len(laps), 6)
        self.assertEqual({lap[:3] for lap in laps}, {("indi", "", "rss_formula_americas_2020_oval")})
        self.assertIn(("indi", "", "rss_formula_americas_2020_oval", "Pod 5", 43019), laps)

    def test_cut_lap_is_skipped(self):
        laps = lbl.parse_log(sample("cut_lap.log"))
        times = {lap[4] for lap in laps}
        self.assertNotIn(70000, times)
        self.assertEqual(min(times), 74595)
        self.assertEqual(laps[0][:3], ("daytona_2017", "oval", "2019_ford_mustang_nascar"))

    def test_log_without_laps_gives_nothing(self):
        self.assertEqual(lbl.parse_log(sample("no_laps.log")), [])

    def test_spectator_is_ignored(self):
        text = make_log(pods=("Pod 3", "Spectator"), laps=[("Spectator", "0:30:000", 0), ("Pod 3", "1:00:000", 0)])
        self.assertEqual([lap[3] for lap in lbl.parse_log(text)], ["Pod 3"])

    def test_time_conversion(self):
        text = make_log(laps=[("Pod 3", "1:36:595", 0)])
        self.assertEqual(lbl.parse_log(text)[0][4], 96595)
        self.assertEqual(lbl.format_time(96595), "1:36.595")
        self.assertEqual(lbl.format_time(28074), "0:28.074")

    def test_lap_without_result_line_is_ignored(self):
        text = make_log(laps=[("Pod 3", "1:00:000", 0)]) + "LAP Pod 3 0:50:000\nSPLIT COUNT: 3\n"
        self.assertEqual([lap[4] for lap in lbl.parse_log(text)], [60000])

    def test_driver_name_with_spaces_and_numeric_name(self):
        text = make_log(pods=("The manager", "4"), laps=[("The manager", "1:00:000", 0), ("4", "2:00:000", 0)])
        self.assertEqual([lap[3] for lap in lbl.parse_log(text)], ["The manager", "4"])

    def test_car_comes_from_pod_mapping(self):
        text = make_log(cars='["car_a", "car_b"]', pods=("Pod 3",), laps=[("Pod 3", "1:00:000", 0)])
        text = text.replace("CAR: 0 car_a", "CAR: 0 car_b")
        self.assertEqual(lbl.parse_log(text)[0][2], "car_b")

    def test_log_without_track_or_cars_gives_nothing(self):
        text = make_log(laps=[("Pod 3", "1:00:000", 0)]).replace("TRACK=", "NOTRACK=")
        self.assertEqual(lbl.parse_log(text), [])

    def test_windows_line_endings(self):
        text = make_log(layout="oval", laps=[("Pod 3", "1:00:000", 0)]).replace("\n", "\r\n")
        self.assertEqual(lbl.parse_log(text), [("indi", "oval", "car_a", "Pod 3", 60000)])


class MergeTests(unittest.TestCase):
    def test_unmapped_ids_fall_back_to_raw_ids_and_are_reported(self):
        unmapped = set()
        names = lbl.resolve_names(ID_MAP, "mystery", "lay", "car_x", unmapped)
        self.assertEqual(names, ("mystery", "lay", "car_x"))
        self.assertEqual(unmapped, {"track mystery", "car car_x"})

    def test_unmapped_layout_of_mapped_track(self):
        unmapped = set()
        names = lbl.resolve_names(ID_MAP, "indi", "other", "rss_formula_americas_2020_oval", unmapped)
        self.assertEqual(names, ("Indianapolis Motor Speedway", "other", "Formula Americas 2020 Oval"))
        self.assertEqual(unmapped, {"layout indi/other"})

    def test_only_faster_lap_replaces_record(self):
        data = {}
        self.assertTrue(lbl.merge_lap(data, "T", "L", "C", "Pod 3", 90000))
        self.assertFalse(lbl.merge_lap(data, "T", "L", "C", "Pod 4", 91000))
        self.assertFalse(lbl.merge_lap(data, "T", "L", "C", "Pod 4", 90000))
        self.assertTrue(lbl.merge_lap(data, "T", "L", "C", "Pod 5", 89999))
        self.assertEqual(data["T"]["L"]["records"],
                         [{"class": "", "car": "C", "driver": "Pod 5", "time": "1:29.999",
                           "source": "ac-server-log"}])

    def test_one_record_per_car_sorted_by_time(self):
        data = {}
        lbl.merge_lap(data, "T", "L", "Slow", "Pod 3", 100000)
        lbl.merge_lap(data, "T", "L", "Fast", "Pod 4", 80000)
        records = lbl.sort_records(data)["T"]["L"]["records"]
        self.assertEqual([r["car"] for r in records], ["Fast", "Slow"])

    def test_hand_edited_driver_survives_when_not_beaten(self):
        data = {"T": {"L": {"records": [{"class": "", "car": "C", "driver": "Jane", "time": "1:30.000"}]}}}
        self.assertFalse(lbl.merge_lap(data, "T", "L", "C", "Pod 3", 95000))
        self.assertEqual(data["T"]["L"]["records"][0]["driver"], "Jane")

    def test_tracks_and_layouts_sort_case_insensitively(self):
        data = {}
        for track, layout in [("b track", "z"), ("Zandvoort", "B"), ("a track", "a"), ("Zandvoort", "a")]:
            lbl.merge_lap(data, track, layout, "C", "Pod 3", 90000)
        out = lbl.sort_records(data)
        self.assertEqual(list(out), ["a track", "b track", "Zandvoort"])
        self.assertEqual(list(out["Zandvoort"]), ["a", "B"])

    def test_parse_time(self):
        self.assertEqual(lbl.parse_time("1:20.942"), 80942)
        self.assertEqual(lbl.parse_time("0:28.07"), 28070)
        self.assertIsNone(lbl.parse_time(""))
        self.assertIsNone(lbl.parse_time(None))


class PassTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.logs = Path(self.tmp.name) / "logs"
        self.logs.mkdir()
        self.out = Path(self.tmp.name) / "best.json"
        self.map_path = Path(self.tmp.name) / "map.json"
        self.map_path.write_text(json.dumps(ID_MAP), encoding="utf-8")

    def run_main(self):
        return lbl.main(["--logs-dir", str(self.logs), "--out", str(self.out),
                         "--map", str(self.map_path), "--once"])

    def test_once_builds_file_and_second_run_is_stable(self):
        (self.logs / "a.log").write_text(sample("two_sessions.log"), encoding="utf-8")
        (self.logs / "b.log").write_text(sample("cut_lap.log"), encoding="utf-8")
        self.assertEqual(self.run_main(), 0)
        first = self.out.read_text(encoding="utf-8")
        data = json.loads(first)
        self.assertEqual(data["Indianapolis Motor Speedway"]["Indianapolis Motor Speedway"]["records"],
                         [{"class": "", "car": "Formula Americas 2020 Oval", "driver": "Pod 5",
                           "time": "0:43.019", "source": "ac-server-log"}])
        self.assertEqual(data["Daytona International Speedway"]["Nascar"]["records"][0]["time"], "1:14.595")
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.out.read_text(encoding="utf-8"), first)

    def test_growing_log_improves_record_and_slower_lap_does_not(self):
        log_path = self.logs / "a.log"
        log_path.write_text(make_log(laps=[("Pod 3", "1:00:000", 0)]), encoding="utf-8")
        self.run_main()
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write("LAP Pod 4 1:05:000\nResult.OnLapCompleted. Cuts: 0\n")
        self.run_main()
        self.assertEqual(self._times(), ["1:00.000"])
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write("LAP Pod 4 0:59:000\nResult.OnLapCompleted. Cuts: 0\n")
        self.run_main()
        self.assertEqual(self._times(), ["0:59.000"])

    def test_restart_without_state_keeps_records(self):
        (self.logs / "a.log").write_text(make_log(laps=[("Pod 3", "1:00:000", 0)]), encoding="utf-8")
        self.run_main()
        Path(str(self.out) + ".state.json").unlink()
        self.run_main()
        self.assertEqual(self._times(), ["1:00.000"])

    def test_unreadable_output_is_not_overwritten(self):
        (self.logs / "a.log").write_text(make_log(laps=[("Pod 3", "1:00:000", 0)]), encoding="utf-8")
        self.out.write_text("{ not json", encoding="utf-8")
        self.assertEqual(self.run_main(), 2)
        self.assertEqual(self.out.read_text(encoding="utf-8"), "{ not json")

    def test_wrong_shape_output_is_not_overwritten(self):
        self.out.write_text('{"T": []}', encoding="utf-8")
        self.assertEqual(self.run_main(), 2)
        self.assertEqual(self.out.read_text(encoding="utf-8"), '{"T": []}')

    def test_hand_edit_between_passes_survives_a_later_write(self):
        (self.logs / "a.log").write_text(make_log(laps=[("Pod 3", "1:00:000", 0)]), encoding="utf-8")
        state, unmapped, reported = {}, set(), set()
        lbl.run_pass(self.logs, self.out, ID_MAP, state, unmapped, reported)
        data = json.loads(self.out.read_text(encoding="utf-8"))
        data["Indianapolis Motor Speedway"]["Indianapolis Motor Speedway"]["records"][0]["driver"] = "Jane"
        self.out.write_text(json.dumps(data), encoding="utf-8")
        (self.logs / "b.log").write_text(
            make_log(track="daytona_2017", layout="oval", laps=[("Pod 4", "2:00:000", 0)]), encoding="utf-8")
        lbl.run_pass(self.logs, self.out, ID_MAP, state, unmapped, reported)
        data = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertEqual(data["Indianapolis Motor Speedway"]["Indianapolis Motor Speedway"]["records"][0]["driver"], "Jane")
        self.assertIn("Daytona International Speedway", data)

    def test_deleted_output_is_rebuilt_from_the_logs(self):
        (self.logs / "a.log").write_text(make_log(laps=[("Pod 3", "1:00:000", 0)]), encoding="utf-8")
        state = {}
        lbl.run_pass(self.logs, self.out, ID_MAP, state, set(), set())
        before = self.out.read_text(encoding="utf-8")
        self.out.unlink()
        lbl.run_pass(self.logs, self.out, ID_MAP, state, set(), set())
        self.assertEqual(self.out.read_text(encoding="utf-8"), before)

    def test_invalid_output_mid_run_skips_the_pass_without_writing(self):
        state = {}
        lbl.run_pass(self.logs, self.out, ID_MAP, state, set(), set())
        self.out.write_text("{ not json", encoding="utf-8")
        (self.logs / "a.log").write_text(make_log(laps=[("Pod 3", "1:00:000", 0)]), encoding="utf-8")
        with self.assertRaises(lbl.OutputError):
            lbl.run_pass(self.logs, self.out, ID_MAP, state, set(), set())
        self.assertEqual(self.out.read_text(encoding="utf-8"), "{ not json")

    def test_missing_logs_dir_fails(self):
        self.logs.rmdir()
        self.assertEqual(self.run_main(), 2)

    def _times(self):
        data = json.loads(self.out.read_text(encoding="utf-8"))
        return [r["time"] for layouts in data.values() for e in layouts.values() for r in e["records"]]


class AtomicWriteTests(unittest.TestCase):
    def test_replaces_file_and_leaves_no_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.json"
            path.write_text("old", encoding="utf-8")
            lbl.atomic_write(path, "new")
            self.assertEqual(path.read_text(encoding="utf-8"), "new")
            self.assertEqual(os.listdir(tmp), ["x.json"])

    def test_retries_permission_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.json"
            real = os.replace
            calls = []

            def flaky(src, dst):
                calls.append(1)
                if len(calls) < 3:
                    raise PermissionError("locked")
                return real(src, dst)

            with mock.patch.object(lbl.os, "replace", flaky), mock.patch.object(lbl, "REPLACE_DELAY", 0):
                lbl.atomic_write(path, "new")
            self.assertEqual(len(calls), 3)
            self.assertEqual(path.read_text(encoding="utf-8"), "new")

    def test_failed_replace_keeps_old_file_and_removes_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.json"
            path.write_text("old", encoding="utf-8")

            def locked(src, dst):
                raise PermissionError("locked")

            with mock.patch.object(lbl.os, "replace", locked), mock.patch.object(lbl, "REPLACE_DELAY", 0):
                with self.assertRaises(PermissionError):
                    lbl.atomic_write(path, "new")
            self.assertEqual(path.read_text(encoding="utf-8"), "old")
            self.assertEqual(os.listdir(tmp), ["x.json"])


if __name__ == "__main__":
    unittest.main()
