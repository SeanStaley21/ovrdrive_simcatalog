import os
import queue
import tempfile
import threading
import unittest
from unittest import mock

import best_laps as bl
import best_laps_tab as tab
import records_editor as editor
import records_file as rf


class ScanWorkerTests(unittest.TestCase):
    def run_worker(self, scan):
        stop, now, results = threading.Event(), threading.Event(), queue.Queue()
        with mock.patch.object(bl, "scan", scan):
            thread = threading.Thread(target=tab.scan_worker, args=("D:/logs", stop, now, results))
            thread.start()
            first = [results.get(timeout=5), results.get(timeout=5)]
            stop.set()
            now.set()
            thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        return first, results

    def test_posts_scanning_then_the_result(self):
        items, rest = self.run_worker(lambda logs_dir, cache: (["lap"], 2, []))
        self.assertEqual(items, [("scanning",), ("ok", ["lap"], 0, 2, [])])
        self.assertTrue(rest.empty())

    def test_cache_size_is_the_total_log_count(self):
        def scan(logs_dir, cache):
            cache.update({"a.log": (1, []), "b.log": (2, [])})
            return [], 1, []

        items, _ = self.run_worker(scan)
        self.assertEqual(items[1], ("ok", [], 2, 1, []))

    def test_logs_folder_error_carries_its_kind(self):
        def scan(logs_dir, cache):
            raise bl.LogsFolderError("not_found", "not found")

        items, _ = self.run_worker(scan)
        self.assertEqual(items[1], ("error", "not_found", "not found"))

    def test_unexpected_error_is_reported_by_type(self):
        def scan(logs_dir, cache):
            raise ValueError("secret detail")

        items, _ = self.run_worker(scan)
        self.assertEqual(items[1], ("error", "failed", "scan failed (ValueError)"))

    def test_check_now_wakes_the_wait_for_another_scan(self):
        stop, now, results = threading.Event(), threading.Event(), queue.Queue()
        with mock.patch.object(bl, "scan", return_value=([], 0, [])):
            thread = threading.Thread(target=tab.scan_worker, args=("D:/logs", stop, now, results))
            thread.start()
            results.get(timeout=5)
            results.get(timeout=5)
            now.set()
            self.assertEqual(results.get(timeout=5), ("scanning",))
            stop.set()
            now.set()
            thread.join(timeout=5)
        self.assertFalse(thread.is_alive())


class PollTests(unittest.TestCase):
    def make_tab(self, *items):
        fake = mock.Mock()
        fake.results = queue.Queue()
        for item in items:
            fake.results.put(item)
        return fake

    def poll(self, fake):
        tab.BestLapsTab.poll(fake)
        return fake.check_button.state.call_args_list

    def test_nothing_queued_leaves_the_button_alone(self):
        fake = self.make_tab()
        self.assertEqual(self.poll(fake), [])
        fake.apply_result.assert_not_called()

    def test_scanning_disables_the_button(self):
        fake = self.make_tab(("scanning",))
        self.assertEqual(self.poll(fake), [mock.call(["disabled"])])
        fake.apply_result.assert_not_called()

    def test_finished_scan_applies_the_newest_result_and_enables_the_button(self):
        newest = ("ok", [], 1, 0, [])
        fake = self.make_tab(("scanning",), ("error", "failed", "x"), ("scanning",), newest)
        self.assertEqual(self.poll(fake), [mock.call(["!disabled"])])
        fake.apply_result.assert_called_once_with(newest)

    def test_a_newer_scan_in_progress_keeps_the_button_disabled(self):
        result = ("ok", [], 1, 0, [])
        fake = self.make_tab(("scanning",), result, ("scanning",))
        self.assertEqual(self.poll(fake), [mock.call(["disabled"])])
        fake.apply_result.assert_called_once_with(result)

    def test_no_worker_does_nothing(self):
        fake = mock.Mock()
        fake.results = None
        self.assertEqual(self.poll(fake), [])


class ApplyResultTests(unittest.TestCase):
    def test_ok_result_stores_laps_and_counts(self):
        fake = mock.Mock()
        tab.BestLapsTab.apply_result(fake, ("ok", ["lap"], 4, 1, [("a.log", "OSError")]))
        self.assertEqual(fake.laps, ["lap"])
        self.assertEqual((fake.outcome[0], fake.outcome[2:]), ("ok", (4, 1, [("a.log", "OSError")])))
        fake.render.assert_called_once()
        fake.show_status.assert_called_once()

    def test_error_result_keeps_kind_and_detail(self):
        fake = mock.Mock()
        tab.BestLapsTab.apply_result(fake, ("error", "unreachable", "(OSError)"))
        self.assertEqual(fake.outcome, ("error", "unreachable", "(OSError)"))


def make_row(ms=80000, matched=True, layout="Full", car="Car A"):
    return bl.BestLap("Track A", layout, car, "Pod 1", ms, "raw", matched, "2026-05-06")


class AddDismissTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.dict(os.environ, {"APPDATA": tmp.name})
        patch.start()
        self.addCleanup(patch.stop)

    def make_tab(self, *rows):
        fake = mock.Mock()
        fake.data = {"Track A": {"Full": {"records": []}}}
        fake.handled = []
        fake.selected_rows.return_value = list(rows)
        fake.add_records.return_value = True
        fake.remember = lambda picked, added=False: tab.BestLapsTab.remember(fake, picked, added)
        return fake

    def test_unmatched_row_is_refused_before_any_prompt(self):
        fake = self.make_tab(make_row(), make_row(matched=False))
        with mock.patch.object(tab, "ask_lap") as ask, mock.patch.object(tab.messagebox, "showerror") as err:
            tab.BestLapsTab.add_selected(fake)
        self.assertEqual(err.call_args.args[1], "Unmatched rows cannot be added.")
        ask.assert_not_called()
        fake.add_records.assert_not_called()
        self.assertFalse(bl.handled_path().exists())

    def test_layout_missing_from_the_file_is_refused(self):
        fake = self.make_tab(make_row(layout="Gone"))
        with mock.patch.object(tab, "ask_lap") as ask, mock.patch.object(tab.messagebox, "showerror") as err:
            tab.BestLapsTab.add_selected(fake)
        self.assertEqual(err.call_args.args[1],
                         "Track A / Gone is not in the records file. Add the layout to the file first.")
        ask.assert_not_called()
        fake.add_records.assert_not_called()

    def test_existing_record_with_the_same_car_and_time_is_refused(self):
        fake = self.make_tab(make_row())
        fake.data["Track A"]["Full"]["records"] = [{"car": "Car A", "time": "1:20.000"}]
        with mock.patch.object(tab, "ask_lap") as ask, mock.patch.object(tab.messagebox, "showerror") as err:
            tab.BestLapsTab.add_selected(fake)
        self.assertEqual(err.call_args.args[1], "Car A already has 1:20.000 on Track A / Full. Dismiss it to hide it.")
        ask.assert_not_called()
        fake.add_records.assert_not_called()

    def test_different_time_or_car_is_still_allowed(self):
        fake = self.make_tab(make_row())
        fake.data["Track A"]["Full"]["records"] = [{"car": "Car A", "time": "1:20.001"},
                                                   {"car": "Car B", "time": "1:20.000"}]
        with mock.patch.object(tab, "ask_lap", return_value={"car": "Car A"}) as ask:
            tab.BestLapsTab.add_selected(fake)
        ask.assert_called_once()
        fake.add_records.assert_called_once()

    def test_cancel_aborts_with_nothing_written(self):
        fake = self.make_tab(make_row(), make_row(car="Car B"))
        with mock.patch.object(tab, "ask_lap", side_effect=[{"car": "Car A"}, None]) as ask:
            tab.BestLapsTab.add_selected(fake)
        self.assertEqual(ask.call_count, 2)
        fake.add_records.assert_not_called()
        self.assertEqual(fake.handled, [])
        self.assertFalse(bl.handled_path().exists())

    def test_successful_add_remembers_the_rows_then_renders(self):
        rows = [make_row(), make_row(car="Car B", ms=90000)]
        fake = self.make_tab(*rows)
        recs = [{"car": "Car A"}, {"car": "Car B"}]
        with mock.patch.object(tab, "ask_lap", side_effect=recs):
            tab.BestLapsTab.add_selected(fake)
        fake.add_records.assert_called_once_with([("Track A", "Full", recs[0]), ("Track A", "Full", recs[1])])
        self.assertEqual(bl.read_handled(), [("Track A", "Full", "Car A", 80000, True),
                                             ("Track A", "Full", "Car B", 90000, True)])
        self.assertIsNone(fake.shown)
        fake.render.assert_called_once()

    def test_failed_add_leaves_the_sidecar_alone(self):
        fake = self.make_tab(make_row())
        fake.add_records.return_value = False
        with mock.patch.object(tab, "ask_lap", return_value={"car": "Car A"}):
            tab.BestLapsTab.add_selected(fake)
        self.assertEqual(fake.handled, [])
        self.assertFalse(bl.handled_path().exists())
        fake.render.assert_not_called()

    def test_dismiss_writes_only_the_sidecar_and_renders(self):
        fake = self.make_tab(make_row(), make_row(matched=False, car="Car Z"))
        tab.BestLapsTab.dismiss_selected(fake)
        fake.add_records.assert_not_called()
        self.assertEqual(len(bl.read_handled()), 2)
        fake.render.assert_called_once()

    def test_unwritable_sidecar_is_reported_but_the_rows_are_hidden(self):
        fake = self.make_tab(make_row())
        with mock.patch.object(bl, "write_handled", side_effect=OSError("denied")):
            tab.BestLapsTab.dismiss_selected(fake)
        self.assertEqual(len(fake.handled), 1)
        self.assertIn("reappear", fake.status.config.call_args.kwargs["text"])
        fake.render.assert_called_once()

    def render(self, handled):
        fake = mock.Mock()
        fake.handled = handled
        fake.shown = []
        fake.laps, fake.data, fake.id_map = [], {}, None
        fake.catalog_tracks, fake.catalog_cars = set(), set()
        fake.tree.selection.return_value = ()
        fake.tree.get_children.return_value = ()
        fake.tree.yview.return_value = (0.0, 1.0)
        rows = [make_row(), make_row(car="Car B", ms=90000)]
        with mock.patch.object(bl, "best_laps", return_value=rows):
            tab.BestLapsTab.render(fake)
        return fake

    def test_render_skips_handled_rows(self):
        fake = self.render([("Track A", "Full", "Car A", 80000)])
        self.assertEqual([row.car for row in fake.row_by_iid.values()], ["Car B"])
        self.assertEqual(fake.tree.insert.call_count, 1)

    def test_deleted_sidecar_brings_rows_back(self):
        bl.write_handled([("Track A", "Full", "Car A", 80000)])
        self.assertEqual(len(self.render(bl.read_handled()).row_by_iid), 1)
        bl.handled_path().unlink()
        self.assertEqual(len(self.render(bl.read_handled()).row_by_iid), 2)


class MatchTests(unittest.TestCase):
    TRACKS = {"Track A::Full", "Track A::Short"}
    CARS = {"Car A", "Car B"}
    ID_MAP = {"tracks": {"ta": {"name": "Track A", "layouts": {"": "Full"}}}, "cars": {"car_b": "Car B"}}

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.dict(os.environ, {"APPDATA": tmp.name})
        patch.start()
        self.addCleanup(patch.stop)

    def unmatched_row(self, **fields):
        values = dict(track="Track A", layout="Full", car="car_z", driver="Pod 1", ms=80000, raw="ta /  / car_z",
                      matched=False, date="2026-05-06", ids=("ta", "", "car_z"), map_track=True, map_car=False)
        return bl.BestLap(**{**values, **fields})

    def make_tab(self, *rows):
        fake = mock.Mock()
        fake.catalog_tracks, fake.catalog_cars = set(self.TRACKS), set(self.CARS)
        fake.matches = {"tracks": {}, "cars": {}}
        fake.id_map = None
        fake.laps = []
        fake.handled = []
        fake.selected_rows.return_value = list(rows)
        return fake

    def match(self, fake, picked):
        with mock.patch.object(tab, "ask_match", return_value=picked) as ask, \
                mock.patch.object(tab.messagebox, "showerror") as err:
            tab.BestLapsTab.match_selected(fake)
        return ask, err

    def test_refusals_never_open_the_dialog(self):
        full = self.unmatched_row(map_car=True)
        cases = {
            "no rows": (self.make_tab(), "Select one row to match."),
            "two rows": (self.make_tab(self.unmatched_row(), self.unmatched_row(ms=81000)),
                         "Select one row to match."),
            "id map matches it": (self.make_tab(full), "This row is matched by the id map."),
        }
        for label, (fake, message) in cases.items():
            with self.subTest(label):
                ask, err = self.match(fake, ("x", "y"))
                self.assertEqual(err.call_args.args[1], message)
                ask.assert_not_called()
        for label, empty in (("tracks", "catalog_tracks"), ("cars", "catalog_cars")):
            with self.subTest(label):
                fake = self.make_tab(self.unmatched_row())
                setattr(fake, empty, set())
                ask, err = self.match(fake, ("x", "y"))
                self.assertIn("data/tracks.json", err.call_args.args[1])
                self.assertIn("data/cars.json", err.call_args.args[1])
                ask.assert_not_called()

    def test_car_match_is_saved_and_applied(self):
        fake = self.make_tab(self.unmatched_row())
        ask, err = self.match(fake, (None, "Car A"))
        ask.assert_called_once_with(fake.root, fake.selected_rows()[0], fake.catalog_tracks, fake.catalog_cars)
        err.assert_not_called()
        self.assertEqual(fake.matches, {"tracks": {}, "cars": {"car_z": "Car A"}})
        self.assertEqual(bl.read_matches(), fake.matches)
        self.assertIsNone(fake.shown)
        fake.render.assert_called_once()

    def test_track_match_is_saved_under_the_raw_ids(self):
        row = self.unmatched_row(track="zz", layout="zz", map_track=False, map_car=True, car="Car A",
                                 ids=("zz", "gp", "car_a"))
        fake = self.make_tab(row)
        self.match(fake, (("Track A", "Short"), None))
        self.assertEqual(bl.read_matches(),
                         {"tracks": {"zz": {"gp": {"track": "Track A", "layout": "Short"}}}, "cars": {}})

    def laps(self, *items):
        return [(track, "", car, "Pod 1", ms, "2026-05-06") for track, car, ms in items]

    def visible(self, fake):
        rows = bl.best_laps(fake.laps, fake.id_map, fake.catalog_tracks, fake.catalog_cars, fake.matches)
        return [(r.track, r.car, r.ms) for r in rows if not bl.is_handled(r, fake.handled)]

    def test_dismissed_while_unmatched_stays_hidden_after_matching(self):
        fake = self.make_tab(self.unmatched_row())
        fake.id_map = self.ID_MAP
        fake.laps = self.laps(("ta", "car_z", 80000), ("ta", "car_z", 82000))
        fake.handled = [("Track A", "Full", "car_z", 80000), ("Track A", "Full", "other", 80000)]
        self.match(fake, (None, "Car A"))
        self.assertEqual(fake.handled, [("Track A", "Full", "Car A", 80000), ("Track A", "Full", "other", 80000)])
        self.assertEqual(bl.read_handled(), fake.handled)
        self.assertEqual(self.visible(fake), [("Track A", "Car A", 82000)])

    def test_car_match_keeps_the_same_car_id_hidden_on_other_tracks(self):
        id_map = {"tracks": {"ta": self.ID_MAP["tracks"]["ta"], "tb": {"name": "Track B", "layouts": {"": "Main"}}},
                  "cars": {}}
        fake = self.make_tab(self.unmatched_row())
        fake.id_map = id_map
        fake.catalog_tracks.add("Track B::Main")
        fake.laps = self.laps(("ta", "car_z", 80000), ("tb", "car_z", 81000))
        fake.handled = [(t, l, "car_z", ms) for t, l, ms in (("Track A", "Full", 80000), ("Track B", "Main", 81000))]
        self.match(fake, (None, "Car A"))
        self.assertEqual(self.visible(fake), [])

    def test_track_match_keeps_the_other_cars_on_the_layout_hidden(self):
        id_map = {"tracks": {}, "cars": {"car_a": "Car A", "car_b": "Car B"}}
        row = self.unmatched_row(track="zz", layout="gp", car="Car A", ids=("zz", "gp", "car_a"),
                                 map_track=False, map_car=True)
        fake = self.make_tab(row)
        fake.id_map = id_map
        fake.laps = [("zz", "gp", "car_a", "Pod 1", 80000, "d"), ("zz", "gp", "car_b", "Pod 1", 81000, "d")]
        fake.handled = [("zz", "gp", "Car A", 80000), ("zz", "gp", "Car B", 81000)]
        self.match(fake, (("Track A", "Short"), None))
        self.assertEqual(self.visible(fake), [])
        self.assertEqual(fake.handled, [("Track A", "Short", "Car A", 80000), ("Track A", "Short", "Car B", 81000)])

    def test_rematching_one_id_leaves_another_id_with_the_old_car_hidden(self):
        id_map = {"tracks": self.ID_MAP["tracks"], "cars": {"car_a": "Car A"}}
        fake = self.make_tab(self.unmatched_row(matched=True, car="Car A"))
        fake.id_map = id_map
        fake.matches["cars"]["car_z"] = "Car A"
        fake.laps = self.laps(("ta", "car_a", 80000), ("ta", "car_z", 81000))
        fake.handled = [("Track A", "Full", "Car A", 80000), ("Track A", "Full", "Car A", 81000)]
        self.match(fake, (None, "Car B"))
        self.assertEqual(self.visible(fake), [])
        self.assertIn(("Track A", "Full", "Car A", 80000), fake.handled)

    def test_cancel_writes_nothing(self):
        fake = self.make_tab(self.unmatched_row())
        self.match(fake, None)
        self.assertEqual(fake.matches, {"tracks": {}, "cars": {}})
        self.assertFalse(bl.matches_path().exists())
        self.assertFalse(bl.handled_path().exists())
        fake.render.assert_not_called()

    def test_failed_write_is_reported_and_kept_in_memory(self):
        fake = self.make_tab(self.unmatched_row())
        with mock.patch.object(bl, "write_matches", side_effect=OSError("denied")):
            self.match(fake, (None, "Car A"))
        self.assertIn("Could not save", fake.status.config.call_args.kwargs["text"])
        self.assertEqual(fake.matches["cars"], {"car_z": "Car A"})
        fake.render.assert_called_once()

    def test_failed_handled_write_keeps_the_saved_match_and_says_so(self):
        fake = self.make_tab(self.unmatched_row())
        with mock.patch.object(bl, "write_handled", side_effect=OSError("denied")):
            self.match(fake, (None, "Car A"))
        self.assertIn("match was saved", fake.status.config.call_args.kwargs["text"])
        self.assertEqual(bl.read_matches(), fake.matches)
        fake.render.assert_called_once()

    def test_added_lap_stays_under_its_names_when_the_match_is_corrected(self):
        fake = self.make_tab(self.unmatched_row())
        fake.id_map = self.ID_MAP
        fake.laps = self.laps(("ta", "car_z", 80000), ("ta", "car_z", 90000))
        fake.add_records.return_value = True
        fake.remember = lambda picked, added=False: tab.BestLapsTab.remember(fake, picked, added)
        fake.data = {"Track A": {"Full": {"records": []}}}
        self.match(fake, (None, "Car A"))
        [shown] = [r for r in bl.best_laps(fake.laps, fake.id_map, fake.catalog_tracks, fake.catalog_cars,
                                           fake.matches) if r.ms == 80000]
        fake.selected_rows.return_value = [shown]
        with mock.patch.object(tab, "ask_lap", return_value={"car": "Car A"}):
            tab.BestLapsTab.add_selected(fake)
        dismissed = [r for r in bl.best_laps(fake.laps, fake.id_map, fake.catalog_tracks, fake.catalog_cars,
                                             fake.matches) if r.ms == 90000]
        fake.selected_rows.return_value = dismissed
        tab.BestLapsTab.dismiss_selected(fake)
        self.assertEqual(self.visible(fake), [])
        fake.selected_rows.return_value = [shown]
        self.match(fake, (None, "Car B"))
        self.assertEqual(self.visible(fake), [("Track A", "Car B", 80000)])
        self.assertIn(("Track A", "Full", "Car A", 80000, True), fake.handled)
        self.assertIn(("Track A", "Full", "Car B", 90000), fake.handled)
        self.assertEqual(bl.read_handled(), fake.handled)

    def test_manually_matched_row_is_added(self):
        row = self.unmatched_row(car="Car A", matched=True)
        fake = mock.Mock()
        fake.data = {"Track A": {"Full": {"records": []}}}
        fake.handled = []
        fake.selected_rows.return_value = [row]
        fake.add_records.return_value = True
        fake.remember = lambda picked, added=False: tab.BestLapsTab.remember(fake, picked, added)
        with mock.patch.object(tab, "ask_lap", return_value={"car": "Car A"}):
            tab.BestLapsTab.add_selected(fake)
        fake.add_records.assert_called_once_with([("Track A", "Full", {"car": "Car A"})])


class AppWriteTests(unittest.TestCase):
    def make_app(self):
        fake = mock.Mock()
        fake.loaded.reformats = False
        return fake

    def write_failing(self, error):
        with mock.patch.object(editor, "save", side_effect=error), \
                mock.patch.object(editor.messagebox, "showerror"):
            return editor.App.write(self.make_app(), lambda data: None)

    def test_saved_but_unreadable_counts_as_written(self):
        self.assertTrue(self.write_failing(rf.SavedButUnreadableError("x")))

    def test_conflict_and_other_errors_are_failures(self):
        self.assertFalse(self.write_failing(rf.ConflictError("x")))
        self.assertFalse(self.write_failing(rf.RecordsFileError("x")))

    def test_declined_reformat_prompt_is_a_failure(self):
        fake = self.make_app()
        fake.loaded.reformats = True
        fake.reformat_confirmed = False
        with mock.patch.object(editor.messagebox, "askokcancel", return_value=False):
            self.assertFalse(editor.App.write(fake, lambda data: None))

    def test_successful_save_is_true(self):
        with mock.patch.object(editor, "save"):
            self.assertTrue(editor.App.write(self.make_app(), lambda data: None))

    def test_add_from_best_laps_adds_every_item_in_one_write(self):
        fake = self.make_app()
        fake.confirm_discard.return_value = True
        fake.write.return_value = True
        items = [("T", "L", {"car": "A", "time": "1:00.000"}), ("T", "L", {"car": "B", "time": "1:00.000"})]
        self.assertTrue(editor.App.add_from_best_laps(fake, items))
        data = {"T": {"L": {"records": []}}}
        fake.write.call_args.args[0](data)
        self.assertEqual([r.get("car") for r in data["T"]["L"]["records"]], ["A", "B", ""])

    def save_batch(self, on_disk):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "userSetRecords.json")
            with open(path, "wb") as handle:
                handle.write(rf.format_text(on_disk, "\n", True).encode("utf-8"))
            before = open(path, "rb").read()
            fake = self.make_app()
            fake.loaded.path = path
            fake.confirm_discard.return_value = True
            fake.write = lambda apply: editor.App.write(fake, apply)
            items = [("T", "L", {"car": "A", "time": "1:00.000"}),
                     ("T", "L", {"car": "B", "time": "1:10.000"})]
            with mock.patch.object(editor.messagebox, "showerror") as err,                     mock.patch.object(editor, "load"):
                result = editor.App.add_from_best_laps(fake, items)
            return result, open(path, "rb").read() == before, err

    def test_duplicate_on_disk_after_load_refuses_the_whole_batch(self):
        blank = {"class": "", "car": "", "driver": "", "time": ""}
        taken = {"class": "GT", "car": "B", "driver": "Ann", "time": "1:10.00"}
        result, unchanged, err = self.save_batch({"T": {"L": {"records": [taken, blank]}}})
        self.assertFalse(result)
        self.assertTrue(unchanged)
        self.assertEqual(err.call_args.args[1], "B already has 1:10.000 on T / L. Dismiss it to hide it.")

    def test_batch_without_a_duplicate_is_written(self):
        blank = {"class": "", "car": "", "driver": "", "time": ""}
        other = {"class": "GT", "car": "B", "driver": "Ann", "time": "1:11.000"}
        result, unchanged, err = self.save_batch({"T": {"L": {"records": [other, blank]}}})
        self.assertTrue(result)
        self.assertFalse(unchanged)
        err.assert_not_called()

    def test_add_from_best_laps_stops_when_unsaved_edits_are_kept(self):
        fake = self.make_app()
        fake.confirm_discard.return_value = False
        self.assertFalse(editor.App.add_from_best_laps(fake, [("T", "L", {})]))
        fake.write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
