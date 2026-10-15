import difflib
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import records_file as rf
from check_track_records import check_record, is_blank

REAL = Path(__file__).resolve().parent.parent / "db" / "userSetRecords.json"
BLANK = {"class": "", "car": "", "driver": "", "time": ""}
REC = {"class": "GT", "car": "Car A", "driver": "Ann", "time": "1:20.942"}


def lf_text():
    text = REAL.read_bytes().decode("utf-8-sig")
    return text.replace("\r\n", "\n")


def sample_data():
    return {
        "Track A": {
            "Layout 1": {"records": [dict(REC), dict(BLANK)]},
            "Layout 2": {"records": [dict(BLANK)]},
        },
        "Track B": {"Full": {"records": [dict(BLANK)]}},
    }


class TempFileCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "db").mkdir()
        self.path = self.root / "db" / "userSetRecords.json"

    def write(self, data, eol="\r\n", bom=False, final_newline=True):
        raw = rf.format_text(data, eol, final_newline).encode("utf-8")
        self.path.write_bytes((rf.BOM if bom else b"") + raw)


class RealFileRoundTrip(unittest.TestCase):
    def test_variants_round_trip(self):
        lf = lf_text()
        variants = [
            (lf, "\n"),
            (lf.replace("\n", "\r\n"), "\r\n"),
        ]
        for text, eol in variants:
            data = rf.parse_text(text)
            self.assertEqual(rf.format_text(data, eol, True), text)

    def test_bom_variant_loads_and_reports_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.json"
            path.write_bytes(rf.BOM + lf_text().replace("\n", "\r\n").encode("utf-8"))
            loaded = rf.load(path)
            self.assertTrue(loaded.bom)
            self.assertEqual(loaded.eol, "\r\n")
            self.assertFalse(loaded.reformats)


class FormatText(unittest.TestCase):
    def fmt(self, data, eol="\n", final=True):
        return rf.format_text(data, eol, final)

    def test_empty_records(self):
        text = self.fmt({"T": {"L": {"records": []}}})
        self.assertIn('      "records": []\n', text)

    def test_no_record_reason_after_and_before_records(self):
        after = {"T": {"L": {"records": [], "no_record_reason": "none"}}}
        before = {"T": {"L": {"no_record_reason": "none", "records": [dict(REC)]}}}
        self.assertIn('      "records": [],\n      "no_record_reason": "none"\n', self.fmt(after))
        text = self.fmt(before)
        self.assertLess(text.index("no_record_reason"), text.index('"records"'))
        self.assertIn('"none",\n      "records": [\n        { "class"', text)
        for data in (after, before):
            self.assertEqual(rf.parse_text(self.fmt(data)), data)

    def test_empty_track_and_top_level(self):
        self.assertEqual(self.fmt({"T": {}}), '{\n  "T": {}\n}\n')
        self.assertEqual(self.fmt({}), "{}\n")
        self.assertEqual(self.fmt({}, final=False), "{}")
        self.assertEqual(self.fmt({"T": {"L": {}}}), '{\n  "T": {\n    "L": {}\n  }\n}\n')

    def test_non_ascii_and_int_year_and_extra_fields(self):
        rec = {"class": "GT", "car": "Citroën", "driver": "Zoë", "time": "1:00.1", "year": 1999, "verified": True}
        text = self.fmt({"Nürburgring": {"Grand Prix": {"records": [rec]}}})
        self.assertIn('"Nürburgring"', text)
        self.assertIn(
            '        { "class": "GT", "car": "Citroën", "driver": "Zoë", "time": "1:00.1", "year": 1999, "verified": true }\n',
            text,
        )

    def test_date_round_trips_in_key_order(self):
        rec = dict(REC, year=2026, date="2026-10-12", verified=True)
        text = self.fmt({"T": {"L": {"records": [rec]}}})
        self.assertIn('"year": 2026, "date": "2026-10-12", "verified": true }', text)
        self.assertEqual(list(rf.parse_text(text)["T"]["L"]["records"][0]), list(rec))

    def test_commas_between_records_only(self):
        text = self.fmt({"T": {"L": {"records": [dict(REC), dict(BLANK)]}}})
        lines = text.split("\n")
        self.assertTrue(lines[4].endswith("},"))
        self.assertTrue(lines[5].endswith("}"))

    def test_crlf_conversion(self):
        text = self.fmt(sample_data(), eol="\r\n")
        self.assertNotIn("\n", text.replace("\r\n", ""))


class ParseRefusals(unittest.TestCase):
    def refused(self, text, *needles):
        with self.assertRaises(rf.RecordsFileError) as ctx:
            rf.parse_text(text)
        for needle in needles:
            self.assertIn(needle, str(ctx.exception))

    def test_duplicates(self):
        self.refused('{"T": {}, "T": {}}', "duplicate", "T")
        self.refused('{"T": {"L": {"records": []}, "L": {"records": []}}}', "T (layout)", "'L'")
        self.refused(
            '{"T": {"L": {"records": [{"class": "a", "class": "b"}]}}}', "T / L record 1", "'class'"
        )

    def test_nested_duplicates_below_record_level(self):
        self.refused(
            '{"T": {"L": {"records": [{"class": "a", "extra": {"k": 1, "k": 2}}]}}}',
            "duplicate key 'k'",
        )

    def test_non_standard_numbers(self):
        self.refused('{"T": {"L": {"records": [{"speed_mph": NaN}]}}}', "NaN", "Line 1")
        self.refused('{"T": {"L": {"records": [{"speed_mph": Infinity}]}}}', "Infinity")

    def test_bad_json_has_line_and_column(self):
        self.refused('{\n  "T": }', "Line 2", "column 8")

    def test_shape(self):
        self.refused("[]", "Top level")
        self.refused('{"T": []}', "T")
        self.refused('{"T": {"L": []}}', "T / L")
        self.refused('{"T": {"L": {}}}', "'records' is missing")
        self.refused('{"T": {"L": {"records": {}}}}', "not a list")
        self.refused('{"T": {"L": {"records": ["x"]}}}', "record 1", "not an object")
        self.refused('{"T": {"L": {"records": [null]}}}', "record 1")
        self.refused('{"A::B": {"L": {"records": []}}}', "::")
        self.refused('{"T": {"A::B": {"records": []}}}', "::")


class Ops(unittest.TestCase):
    def records(self, data, layout="Layout 1"):
        return data["Track A"][layout]["records"]

    def test_add_before_trailing_blank(self):
        data = sample_data()
        new = dict(REC, driver="Bob")
        rf.add(data, "Track A", "Layout 1", new)
        self.assertEqual(self.records(data), [REC, new, BLANK])

    def test_add_to_blank_only_layout(self):
        data = sample_data()
        rf.add(data, "Track A", "Layout 2", dict(REC))
        self.assertEqual(self.records(data, "Layout 2"), [REC, BLANK])

    def test_replace(self):
        data = sample_data()
        new = dict(REC, driver="Bob")
        rf.replace(data, "Track A", "Layout 1", dict(REC), new)
        self.assertEqual(self.records(data), [new, BLANK])

    def test_delete_keeps_one_blank(self):
        data = sample_data()
        rf.delete(data, "Track A", "Layout 1", dict(REC))
        self.assertEqual(self.records(data), [BLANK])

    def test_missing_original_conflicts(self):
        data = sample_data()
        with self.assertRaises(rf.ConflictError):
            rf.delete(data, "Track A", "Layout 1", dict(REC, driver="Other"))
        with self.assertRaises(rf.ConflictError):
            rf.replace(data, "Track A", "Layout 1", dict(REC, driver="Other"), dict(REC))

    def test_missing_layout_conflicts(self):
        data = sample_data()
        with self.assertRaises(rf.ConflictError):
            rf.add(data, "Track A", "Nope", dict(REC))
        with self.assertRaises(rf.ConflictError):
            rf.add(data, "Nope", "Layout 1", dict(REC))

    def test_add_to_empty_records_list(self):
        data = sample_data()
        data["Track A"]["Layout 2"]["records"] = []
        rf.add(data, "Track A", "Layout 2", dict(REC))
        self.assertEqual(self.records(data, "Layout 2"), [REC, BLANK])

    def test_replace_keeps_extra_fields_and_key_order(self):
        data = sample_data()
        old = dict(REC, year=2020, verified=True)
        data["Track A"]["Layout 1"]["records"] = [dict(old), dict(BLANK)]
        new = rf.build_record("GT", "Car A", "Bob", "1:20.942", "2020", "", base=old)
        rf.replace(data, "Track A", "Layout 1", old, new)
        stored = self.records(data)[0]
        self.assertEqual(list(stored), ["class", "car", "driver", "time", "year", "verified"])
        self.assertEqual(stored["driver"], "Bob")
        self.assertTrue(stored["verified"])

    def test_multiple_blanks_collapse_to_one(self):
        data = sample_data()
        data["Track A"]["Layout 1"]["records"] = [dict(BLANK), dict(REC), dict(BLANK), dict(BLANK)]
        new = dict(REC, driver="Bob")
        rf.add(data, "Track A", "Layout 1", new)
        self.assertEqual(self.records(data), [REC, new, BLANK])

    def test_missing_track_or_layout_conflicts_and_creates_nothing(self):
        for track, layout in (("Nope", "Layout 1"), ("Track A", "Nope")):
            for call in (
                lambda d: rf.add(d, track, layout, dict(REC)),
                lambda d: rf.replace(d, track, layout, dict(REC), dict(REC, driver="Bob")),
                lambda d: rf.delete(d, track, layout, dict(REC)),
            ):
                data = sample_data()
                with self.assertRaises(rf.ConflictError):
                    call(data)
                self.assertEqual(data, sample_data())


class CheckRecordDate(unittest.TestCase):
    def problems_for(self, **extra):
        problems = []
        check_record(dict(REC, **extra), "r", problems, {})
        return problems

    def test_valid_dates_pass(self):
        for good in ("2026-10-12", "2024-02-29", "1999-12-31"):
            with self.subTest(good=good):
                self.assertEqual(self.problems_for(date=good), [])

    def test_year_and_date_together_pass(self):
        self.assertEqual(self.problems_for(year=2026, date="2026-10-12"), [])

    def test_year_not_matching_date_is_a_problem(self):
        self.assertEqual(
            self.problems_for(year=2020, date="2026-10-12"),
            ["r: 'year' does not match the year in 'date'"],
        )

    def test_boolean_year_is_only_a_whole_number_problem(self):
        self.assertEqual(
            self.problems_for(year=True, date="2026-10-12"),
            ["r: 'year' must be a whole number"],
        )

    def test_bad_dates_refused_with_message(self):
        bad_values = (
            "2026-13-40", "2025-02-29", "2026-00-10", "10/12/2026", "2026-1-5",
            "20261012", " 2026-10-12", "2026-10-12 ", "2026-10-12\n", "", "\u0662\u0660\u0662\u0666-10-12",
            2026, None, True, 20261012.0, ["2026-10-12"],
        )
        for bad in bad_values:
            with self.subTest(bad=bad):
                self.assertEqual(
                    self.problems_for(date=bad),
                    ["r: 'date' must be a real date written YYYY-MM-DD (e.g. 2026-10-12)"],
                )


class BuildRecord(unittest.TestCase):
    def test_strips_and_omits_empty_year(self):
        rec = rf.build_record(" GT ", " Car A ", " Ann ", " 1:20.942 ", "", "")
        self.assertEqual(rec, REC)

    def test_year_is_int(self):
        rec = rf.build_record("GT", "Car A", "Ann", "1:20.942", " 2020 ", "")
        self.assertEqual(rec["year"], 2020)

    def test_empty_year_removes_existing_year(self):
        rec = rf.build_record("GT", "Car A", "Ann", "1:20.942", "", "", base=dict(REC, year=2020))
        self.assertNotIn("year", rec)

    def test_base_extra_fields_kept(self):
        rec = rf.build_record("GT", "Car A", "Ann", "1:20.942", "", "", base=dict(REC, verified=True))
        self.assertTrue(rec["verified"])

    def test_bad_years_refused(self):
        for bad in ("abc", "1899", "-1", "2020.5"):
            with self.assertRaises(rf.RecordsFileError):
                rf.build_record("GT", "Car A", "Ann", "1:20.942", bad, "")

    def test_date_is_stripped_and_set(self):
        rec = rf.build_record("GT", "Car A", "Ann", "1:20.942", "", " 2026-10-12 ")
        self.assertEqual(rec["date"], "2026-10-12")

    def test_year_not_matching_date_refused(self):
        with self.assertRaises(rf.RecordsFileError) as caught:
            rf.build_record("GT", "Car A", "Ann", "1:20.942", "2020", "2026-10-12")
        self.assertIn("'year' does not match the year in 'date'", str(caught.exception))

    def test_bad_time_and_year_mismatch_both_reported(self):
        with self.assertRaises(rf.RecordsFileError) as caught:
            rf.build_record("GT", "Car A", "Ann", "bad", "2020", "2026-10-12")
        message = str(caught.exception)
        self.assertIn("must look like m:ss.mmm", message)
        self.assertIn("'year' does not match the year in 'date'", message)

    def test_year_matching_date_accepted(self):
        rec = rf.build_record("GT", "Car A", "Ann", "1:20.942", "2026", "2026-10-12")
        self.assertEqual((rec["year"], rec["date"]), (2026, "2026-10-12"))

    def test_empty_date_removes_existing_date(self):
        rec = rf.build_record("GT", "Car A", "Ann", "1:20.942", "", "  ", base=dict(REC, date="2026-10-12"))
        self.assertNotIn("date", rec)

    def test_bad_date_refused(self):
        for bad in ("2026-13-40", "10/12/2026", "abc"):
            with self.subTest(bad=bad):
                with self.assertRaises(rf.RecordsFileError) as caught:
                    rf.build_record("GT", "Car A", "Ann", "1:20.942", "", bad)
                self.assertIn("'date' must be a real date", str(caught.exception))

    def test_new_date_is_appended_after_existing_keys(self):
        rec = rf.build_record("GT", "Car A", "Ann", "1:20.942", "2026", "2026-10-12", base=dict(REC, year=2026, verified=True))
        self.assertEqual(list(rec), ["class", "car", "driver", "time", "year", "verified", "date"])

    def test_edit_keeps_date_position(self):
        old = dict(REC, date="2026-10-12", verified=True)
        rec = rf.build_record("GT", "Car A", "Bob", "1:20.942", "", "2026-10-13", base=old)
        self.assertEqual(list(rec), ["class", "car", "driver", "time", "date", "verified"])
        self.assertEqual(rec["date"], "2026-10-13")

    def test_checker_problems_refused(self):
        with self.assertRaises(rf.RecordsFileError):
            rf.build_record("GT", "Car A", "Ann", "bad", "", "")
        with self.assertRaises(rf.RecordsFileError):
            rf.build_record("GT", "", "Ann", "1:20.942", "", "")

    def test_empty_driver_unknown_and_empty_class_refused(self):
        for args in (("GT", "Car A", "  ", "1:20.942"),
                     ("Nope", "Car A", "Ann", "1:20.942"),
                     ("", "Car A", "Ann", "1:20.942")):
            with self.assertRaises(rf.RecordsFileError):
                rf.build_record(*args, "", "")

    def test_year_above_next_year_refused(self):
        too_far = str(date.today().year + 2)
        with self.assertRaises(rf.RecordsFileError):
            rf.build_record("GT", "Car A", "Ann", "1:20.942", too_far, "")
        self.assertEqual(
            rf.build_record("GT", "Car A", "Ann", "1:20.942", str(date.today().year + 1), "")["year"],
            date.today().year + 1)


class FilterCars(unittest.TestCase):
    CARS = ["Cup MX5", "Mazda MX-5", "MX5 Cup", "Audi R8", "Zonda MX5",
            "Porsche 911 GT3", "Ferrari 488", "Lime Rock Raceway"]

    def test_substring_case_insensitive(self):
        self.assertEqual(rf.filter_cars(self.CARS, "r8"), ["Audi R8"])

    def test_prefix_matches_first_then_sorted(self):
        self.assertEqual(rf.filter_cars(self.CARS, "mx5"),
                         ["MX5 Cup", "Cup MX5", "Mazda MX-5", "Zonda MX5"])

    def test_dash_ignored(self):
        self.assertIn("Mazda MX-5", rf.filter_cars(self.CARS, "mx5"))
        self.assertIn("Mazda MX-5", rf.filter_cars(self.CARS, "MX 5"))

    def test_spacing_ignored(self):
        self.assertEqual(rf.filter_cars(self.CARS, "limerock"), ["Lime Rock Raceway"])
        self.assertEqual(rf.filter_cars(self.CARS, "Lime  Rock"), ["Lime Rock Raceway"])

    def test_typo_tolerated(self):
        self.assertEqual(rf.filter_cars(self.CARS, "porshe"), ["Porsche 911 GT3"])
        self.assertEqual(rf.filter_cars(self.CARS, "ferrai"), ["Ferrari 488"])

    def test_typo_matches_listed_last(self):
        names = ["Alpha Porshe", "Porsche X", "Zed Porsche"]
        self.assertEqual(rf.match_names(names, "porsche"),
                         ["Porsche X", "Zed Porsche", "Alpha Porshe"])

    def test_empty_text_returns_all(self):
        self.assertEqual(rf.filter_cars(self.CARS, ""), self.CARS)
        self.assertEqual(rf.filter_cars(self.CARS, "  "), self.CARS)

    def test_gibberish_returns_empty(self):
        self.assertEqual(rf.filter_cars(self.CARS, "zzz"), [])
        self.assertEqual(rf.filter_cars(self.CARS, "qxv"), [])

    def test_short_text_not_fuzzy(self):
        self.assertEqual(rf.filter_cars(self.CARS, "r9"), [])

    def test_no_duplicates(self):
        self.assertEqual(rf.match_names(["A1", "A1"], "a"), ["A1"])


class SnapCar(unittest.TestCase):
    CARS = {"Mazda MX-5 Cup", "Audi R8", "Audi R-8"}

    def test_normalized_match_snaps(self):
        self.assertEqual(rf.snap_car(self.CARS, "mazda mx5 cup"), "Mazda MX-5 Cup")

    def test_no_match_unchanged(self):
        self.assertEqual(rf.snap_car(self.CARS, "Foo Car"), "Foo Car")

    def test_ambiguous_unchanged(self):
        self.assertEqual(rf.snap_car(self.CARS, "audi r8"), "audi r8")

    def test_empty_unchanged(self):
        self.assertEqual(rf.snap_car(self.CARS, "  "), "  ")


class Save(TempFileCase):
    def line_changes(self, before, after):
        a = before.decode("utf-8").split("\r\n")
        b = after.decode("utf-8").split("\r\n")
        return [d for d in difflib.ndiff(a, b) if d[0] in "+-"]

    def test_only_touched_layout_changes(self):
        self.write(sample_data())
        before = self.path.read_bytes()
        new = dict(REC, driver="Bob")
        loaded = rf.save(self.path, lambda d: rf.add(d, "Track A", "Layout 1", new))
        after = self.path.read_bytes()
        changes = self.line_changes(before, after)
        self.assertEqual(len(changes), 1)
        self.assertIn("Bob", changes[0])
        self.assertIn(b"\r\n", after)
        self.assertNotIn(b"\n", after.replace(b"\r\n", b""))
        self.assertEqual(loaded.data["Track A"]["Layout 1"]["records"][1], new)
        self.assertEqual(os.listdir(self.path.parent), [self.path.name])

    def test_date_added_changes_one_line_and_keeps_crlf(self):
        self.write(sample_data())
        before = self.path.read_bytes()
        new = rf.build_record("GT", "Car A", "Ann", "1:20.942", "", "2026-10-12", base=dict(REC))

        def apply(data):
            rf.replace(data, "Track A", "Layout 1", dict(REC), new)

        loaded = rf.save(self.path, apply)
        after = self.path.read_bytes()
        changes = self.line_changes(before, after)
        self.assertEqual(len(changes), 2)
        self.assertTrue(any('"date": "2026-10-12"' in c for c in changes))
        self.assertNotIn(b"\n", after.replace(b"\r\n", b""))
        self.assertEqual(loaded.data["Track A"]["Layout 1"]["records"][0]["date"], "2026-10-12")

    def test_clearing_date_returns_original_bytes(self):
        self.write(sample_data())
        original = self.path.read_bytes()
        dated = rf.build_record("GT", "Car A", "Ann", "1:20.942", "", "2026-10-12", base=dict(REC))
        rf.save(self.path, lambda d: rf.replace(d, "Track A", "Layout 1", dict(REC), dated))
        cleared = rf.build_record("GT", "Car A", "Ann", "1:20.942", "", "", base=dated)
        rf.save(self.path, lambda d: rf.replace(d, "Track A", "Layout 1", dated, cleared))
        self.assertEqual(self.path.read_bytes(), original)

    def test_bom_and_lf_preserved(self):
        self.write(sample_data(), eol="\n", bom=True, final_newline=False)
        rf.save(self.path, lambda d: rf.add(d, "Track A", "Layout 2", dict(REC)))
        raw = self.path.read_bytes()
        self.assertTrue(raw.startswith(rf.BOM))
        self.assertNotIn(b"\r", raw)
        self.assertFalse(raw.endswith(b"\n"))

    def test_saved_records_pass_checker(self):
        self.write(sample_data())
        loaded = rf.save(self.path, lambda d: rf.add(d, "Track A", "Layout 1", dict(REC, driver="Bob")))
        for layouts in loaded.data.values():
            for entry in layouts.values():
                for rec in entry["records"]:
                    if not is_blank(rec):
                        problems = []
                        check_record(rec, "r", problems, {})
                        self.assertEqual(problems, [])

    def test_replace_retries_then_succeeds(self):
        self.write(sample_data())
        real = os.replace
        calls = {"n": 0}

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise PermissionError("locked")
            real(src, dst)

        with mock.patch("records_file.os.replace", flaky), mock.patch("records_file.time.sleep") as sleep:
            rf.save(self.path, lambda d: rf.add(d, "Track A", "Layout 1", dict(REC, driver="Bob")))
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [0.2, 0.4])
        self.assertIn(b"Bob", self.path.read_bytes())

    def test_permanent_lock_leaves_file_and_cleans_tmp(self):
        self.write(sample_data())
        before = self.path.read_bytes()
        with mock.patch("records_file.os.replace", side_effect=PermissionError("locked")), mock.patch(
            "records_file.time.sleep"
        ) as sleep:
            with self.assertRaises(rf.RecordsFileError) as ctx:
                rf.save(self.path, lambda d: rf.add(d, "Track A", "Layout 1", dict(REC, driver="Bob")))
        self.assertEqual(sleep.call_count, 5)
        self.assertIn("locked by another program", str(ctx.exception))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(os.listdir(self.path.parent), [self.path.name])

    def test_other_layout_change_between_load_and_save_is_kept(self):
        self.write(sample_data())
        rf.load(self.path)
        other = sample_data()
        other["Track B"]["Full"]["records"].insert(0, dict(REC, driver="Elsewhere"))
        self.write(other)
        rf.save(self.path, lambda d: rf.add(d, "Track A", "Layout 1", dict(REC, driver="Bob")))
        text = self.path.read_bytes().decode("utf-8")
        self.assertIn("Elsewhere", text)
        self.assertIn("Bob", text)

    def test_changed_target_conflicts_and_file_unchanged(self):
        self.write(sample_data())
        changed = sample_data()
        changed["Track A"]["Layout 1"]["records"][0]["driver"] = "Changed"
        self.write(changed)
        before = self.path.read_bytes()
        with self.assertRaises(rf.ConflictError):
            rf.save(self.path, lambda d: rf.delete(d, "Track A", "Layout 1", dict(REC)))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(os.listdir(self.path.parent), [self.path.name])

    def test_duplicates_introduced_between_load_and_save_refused(self):
        self.write(sample_data())
        rf.load(self.path)
        text = self.path.read_bytes().decode("utf-8").replace('"Track B": {', '"Track A": {', 1)
        self.path.write_bytes(text.encode("utf-8"))
        before = self.path.read_bytes()
        with self.assertRaises(rf.RecordsFileError):
            rf.save(self.path, lambda d: rf.add(d, "Track A", "Layout 1", dict(REC)))
        self.assertEqual(self.path.read_bytes(), before)

    def test_lone_surrogate_refused_and_nothing_written(self):
        self.write(sample_data())
        before = self.path.read_bytes()
        bad = dict(REC, driver=chr(0xD800))
        with self.assertRaises(rf.RecordsFileError) as ctx:
            rf.save(self.path, lambda d: rf.add(d, "Track A", "Layout 1", bad))
        self.assertIn("Nothing was changed", str(ctx.exception))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(os.listdir(self.path.parent), [self.path.name])

    def test_reread_failure_reports_file_was_saved(self):
        self.write(sample_data())
        with mock.patch("records_file.load", side_effect=rf.RecordsFileError("boom")):
            with self.assertRaises(rf.SavedButUnreadableError) as ctx:
                rf.save(self.path, lambda d: rf.add(d, "Track A", "Layout 1", dict(REC, driver="Bob")))
        self.assertIn("WAS saved", str(ctx.exception))
        self.assertIn(b"Bob", self.path.read_bytes())


class Load(TempFileCase):
    def test_warnings_for_bad_records_do_not_block(self):
        data = sample_data()
        data["Track A"]["Layout 1"]["records"][0]["time"] = "bad"
        self.write(data)
        loaded = rf.load(self.path)
        self.assertTrue(any("time" in w for w in loaded.warnings))
        self.assertFalse(loaded.reformats)

    def test_reformat_warning_names_line(self):
        self.write(sample_data())
        text = self.path.read_bytes().decode("utf-8").replace("{ \"class\"", "{\"class\"", 1)
        self.path.write_bytes(text.encode("utf-8"))
        loaded = rf.load(self.path)
        self.assertTrue(loaded.reformats)
        self.assertTrue(any("line 5" in w for w in loaded.warnings))

    def test_mixed_line_endings_warn(self):
        self.write(sample_data())
        text = self.path.read_bytes().decode("utf-8")
        text = text.replace("\r\n", "\n", 2)
        self.path.write_bytes(text.encode("utf-8"))
        loaded = rf.load(self.path)
        self.assertEqual(loaded.eol, "\r\n")
        self.assertTrue(any("mixes" in w for w in loaded.warnings))
        self.assertTrue(loaded.reformats)

    def test_load_cars_with_sibling_file(self):
        (self.root / "data").mkdir()
        (self.root / "data" / "cars.json").write_text(
            json.dumps({"cars": {"zeta": {}, "Alpha": {}}}), encoding="utf-8-sig"
        )
        data = sample_data()
        data["Track A"]["Layout 1"]["records"][0]["car"] = "beta"
        self.assertEqual(rf.load_cars(self.path, data), ["Alpha", "beta", "zeta"])

    def test_load_catalog_cars_excludes_record_cars(self):
        (self.root / "data").mkdir()
        (self.root / "data" / "cars.json").write_text(json.dumps({"cars": {"Alpha": {}}}), encoding="utf-8")
        self.assertEqual(rf.load_catalog_cars(self.path), {"Alpha"})
        self.assertEqual(rf.load_catalog_cars(self.root / "data" / "x" / "y.json"), set())

    def test_load_catalog_tracks_reads_the_catalog(self):
        (self.root / "data").mkdir()
        (self.root / "data" / "tracks.json").write_text(
            json.dumps({"tracks": {"T::L": {}}}), encoding="utf-8")
        self.assertEqual(rf.load_catalog_tracks(self.path), {"T::L"})
        self.assertEqual(rf.load_catalog_tracks(self.root / "data" / "x" / "y.json"), set())

    def test_load_cars_fallback_when_missing(self):
        self.assertEqual(rf.load_cars(self.path, sample_data()), ["Car A"])


class Config(unittest.TestCase):
    def test_round_trip_and_missing(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"APPDATA": tmp}):
            self.assertIsNone(rf.read_saved_path())
            rf.write_saved_path("C:/x/y.json")
            self.assertEqual(rf.read_saved_path(), "C:/x/y.json")
            rf.config_path().write_text("not json", encoding="utf-8")
            self.assertIsNone(rf.read_saved_path())

    def test_logs_dir_and_records_path_keep_each_other(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"APPDATA": tmp}):
            self.assertIsNone(rf.read_logs_dir())
            rf.write_logs_dir("C:/logs")
            rf.write_saved_path("C:/x/y.json")
            self.assertEqual(rf.read_logs_dir(), "C:/logs")
            self.assertEqual(rf.read_saved_path(), "C:/x/y.json")
            rf.write_logs_dir("C:/other")
            self.assertEqual(rf.read_logs_dir(), "C:/other")
            self.assertEqual(rf.read_saved_path(), "C:/x/y.json")

    def test_old_format_file_has_no_logs_dir(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"APPDATA": tmp}):
            rf.config_path().parent.mkdir(parents=True)
            rf.config_path().write_text(json.dumps({"records_path": "C:/x/y.json"}), encoding="utf-8")
            self.assertIsNone(rf.read_logs_dir())
            self.assertEqual(rf.read_saved_path(), "C:/x/y.json")

    def test_non_dict_config_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"APPDATA": tmp}):
            rf.config_path().parent.mkdir(parents=True)
            rf.config_path().write_text(json.dumps(["C:/logs"]), encoding="utf-8")
            self.assertIsNone(rf.read_logs_dir())
            self.assertEqual(rf.read_config(), {})


if __name__ == "__main__":
    unittest.main()
