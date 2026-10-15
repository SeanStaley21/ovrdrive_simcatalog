import queue
import threading
import unittest
from unittest import mock

import best_laps as bl
import best_laps_tab as tab


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


if __name__ == "__main__":
    unittest.main()
