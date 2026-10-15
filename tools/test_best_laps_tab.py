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
        fake.remember = lambda picked: tab.BestLapsTab.remember(fake, picked)
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
        self.assertEqual(bl.read_handled(), [("Track A", "Full", "Car A", 80000),
                                             ("Track A", "Full", "Car B", 90000)])
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
        items = [("T", "L", {"car": "A"}), ("T", "L", {"car": "B"})]
        self.assertTrue(editor.App.add_from_best_laps(fake, items))
        data = {"T": {"L": {"records": []}}}
        fake.write.call_args.args[0](data)
        self.assertEqual([r.get("car") for r in data["T"]["L"]["records"]], ["A", "B", ""])

    def test_add_from_best_laps_stops_when_unsaved_edits_are_kept(self):
        fake = self.make_app()
        fake.confirm_discard.return_value = False
        self.assertFalse(editor.App.add_from_best_laps(fake, [("T", "L", {})]))
        fake.write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
