"""The Best Laps tab: a background scan of the AC server logs shown next to the records.

Laps can be added to the records file or dismissed."""
import copy
import json
import queue
import threading
from datetime import datetime
import tkinter as tk
from tkinter import messagebox, ttk

import best_laps as bl
import log_best_laps as lbl
from check_track_records import CLASSES
from records_file import RecordsFileError, load_catalog_cars, load_catalog_tracks, match_names

TITLE = "Best Laps"
POLL_MS = 500
NO_FOLDER_MESSAGE = "Best laps: no logs folder set (File > Set logs folder...)"
COLUMNS = (("track", "Track", 180), ("layout", "Layout", 160), ("car", "Car", 200),
           ("driver", "Pod/Driver", 100), ("time", "Time", 90), ("status", "Status", 220))
NO_ID_MAP = {"tracks": {}, "cars": {}}
NAVIGATION_KEYS = {"Up", "Down", "Left", "Right", "Home", "End", "Prior", "Next", "Return", "Escape", "Tab"}


def scan_worker(logs_dir, stop_event, scan_now, results):
    """Post "scanning", scan, post the outcome, then wait for the interval or a Check now."""
    cache = {}
    while not stop_event.is_set():
        results.put(("scanning",))
        try:
            laps, files, unreadable = bl.scan(logs_dir, cache)
            results.put(("ok", laps, len(cache), files, unreadable))
        except bl.LogsFolderError as exc:
            results.put(("error", exc.kind, str(exc)))
        except Exception as exc:
            results.put(("error", "failed", f"scan failed ({type(exc).__name__})"))
        scan_now.wait(bl.INTERVAL)
        scan_now.clear()


def ask_lap(root, row):
    """Ask for the name, class and date of row's lap. Returns the record, or None if cancelled."""
    dialog = tk.Toplevel(root)
    dialog.title("Add lap")
    dialog.transient(root)
    dialog.resizable(False, False)
    name = tk.StringVar(value=row.driver)
    cls = tk.StringVar()
    date_text = tk.StringVar(value=row.date)
    result = []
    form = ttk.Frame(dialog, padding=10)
    form.pack(fill="both", expand=True)
    ttk.Label(form, text=f"{row.track} / {row.layout} / {row.car}  {lbl.format_time(row.ms)}").grid(
        row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
    for index, (label, var) in enumerate((("Name", name), ("Class", cls), ("Date (log file date)", date_text)), 1):
        ttk.Label(form, text=label).grid(row=index, column=0, sticky="w", pady=2)
        if label == "Class":
            widget = ttk.Combobox(form, textvariable=var, values=CLASSES, state="readonly", width=28)
        else:
            widget = ttk.Entry(form, textvariable=var, width=30)
        widget.grid(row=index, column=1, sticky="ew", padx=(8, 0), pady=2)

    def confirm():
        try:
            rec = bl.lap_record(row, name.get(), cls.get(), date_text.get())
        except RecordsFileError as err:
            messagebox.showerror(TITLE, str(err), parent=dialog)
            return
        result.append(rec)
        dialog.destroy()

    buttons = ttk.Frame(form)
    buttons.grid(row=5, column=0, columnspan=2, sticky="e", pady=(8, 0))
    ttk.Label(form, text="The date is the log file's last-modified date; edit it if needed (YYYY-MM-DD).",
              wraplength=300).grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))
    ttk.Button(buttons, text="OK", command=confirm).pack(side="left")
    ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="left", padx=(6, 0))
    dialog.bind("<Return>", lambda _e: confirm())
    dialog.bind("<Escape>", lambda _e: dialog.destroy())
    dialog.grab_set()
    dialog.wait_window()
    return result[0] if result else None


def ask_match(root, row, catalog_tracks, catalog_cars):
    """Ask which catalog track, layout and car row's ids belong to.

    Returns (track, layout) or None, and car or None, for the parts the id map does not already resolve;
    returns None if cancelled.
    """
    layouts = bl.catalog_layouts(catalog_tracks)
    cars = sorted(catalog_cars)
    dialog = tk.Toplevel(root)
    dialog.title("Match lap")
    dialog.transient(root)
    dialog.resizable(False, False)
    track = tk.StringVar(value=row.track if row.track in layouts else "")
    layout = tk.StringVar(value=row.layout if row.layout in layouts.get(row.track, ()) else "")
    car = tk.StringVar(value=row.car if row.car in catalog_cars else "")
    error = tk.StringVar()
    result = []
    form = ttk.Frame(dialog, padding=10)
    form.pack(fill="both", expand=True)
    ttk.Label(form, text=f"Ids: {row.raw}").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))

    def field(index, label, var, names, fixed):
        ttk.Label(form, text=label).grid(row=index, column=0, sticky="w", pady=2)
        if fixed:
            widget = ttk.Label(form, text=var.get())
        else:
            widget = ttk.Combobox(form, textvariable=var, values=names(), width=40)

            def on_key(event):
                if event.keysym not in NAVIGATION_KEYS:
                    widget.config(values=match_names(names(), var.get()))
            widget.bind("<KeyRelease>", on_key)
        widget.grid(row=index, column=1, sticky="ew", padx=(8, 0), pady=2)
        return widget

    field(1, "Track", track, lambda: sorted(layouts), row.map_track)
    layout_box = field(2, "Layout", layout, lambda: layouts.get(track.get(), []), row.map_track)
    if not row.map_track:
        track.trace_add("write", lambda *_: layout_box.config(values=layouts.get(track.get(), [])))
    field(3, "Car", car, lambda: cars, row.map_car)

    def confirm():
        message = bl.check_match(catalog_tracks, catalog_cars,
                                 None if row.map_track else track.get(),
                                 None if row.map_track else layout.get(),
                                 None if row.map_car else car.get())
        if message:
            error.set(message)
            return
        result.append(((None if row.map_track else (track.get(), layout.get())),
                       None if row.map_car else car.get()))
        dialog.destroy()

    ttk.Label(form, textvariable=error, foreground="red", wraplength=300).grid(
        row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))
    buttons = ttk.Frame(form)
    buttons.grid(row=5, column=0, columnspan=2, sticky="e", pady=(8, 0))
    ttk.Button(buttons, text="OK", command=confirm).pack(side="left")
    ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="left", padx=(6, 0))
    dialog.bind("<Return>", lambda _e: confirm())
    dialog.bind("<Escape>", lambda _e: dialog.destroy())
    dialog.grab_set()
    dialog.wait_window()
    return result[0] if result else None


class BestLapsTab:
    def __init__(self, root, notebook, before, add_records):
        self.root = root
        self.add_records = add_records
        self.handled = bl.read_handled()
        self.matches = bl.read_matches()
        self.row_by_iid = {}
        self.logs_dir = None
        self.laps = []
        self.outcome = None
        self.data = {}
        self.id_map = None
        self.catalog_tracks = set()
        self.catalog_cars = set()
        self.shown = []
        self.stop_event = None
        self.scan_now = None
        self.results = None

        self.status = ttk.Label(root, anchor="w", relief="sunken")
        self.status.pack(side="bottom", fill="x", before=before)

        frame = ttk.Frame(notebook, padding=6)
        notebook.add(frame, text="Best Laps")
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(0, 6))
        self.check_button = ttk.Button(buttons, text="Check now", command=self.check_now,
                                       state="disabled")
        self.check_button.pack(side="left")
        ttk.Button(buttons, text="Add...", command=self.add_selected).pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="Match...", command=self.match_selected).pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="Dismiss", command=self.dismiss_selected).pack(side="left", padx=(6, 0))
        table = ttk.Frame(frame)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=[c[0] for c in COLUMNS], show="headings",
                                 height=8, selectmode="extended")
        for key, title, width in COLUMNS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor="w")
        self.tree.tag_configure("unmatched", foreground="gray50")
        bar = ttk.Scrollbar(table, command=self.tree.yview)
        self.tree.config(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        self.poll_id = self.root.after(POLL_MS, self.poll)
        self.show_status()

    # ---- inputs ----

    def set_records(self, loaded):
        self.data = loaded.data
        self.id_map = bl.load_editor_id_map(loaded.path)
        self.catalog_tracks = load_catalog_tracks(loaded.path)
        self.catalog_cars = load_catalog_cars(loaded.path)
        self.render()
        self.show_status()

    def set_logs_dir(self, path):
        self.stop_worker()
        self.logs_dir = path or None
        self.laps = []
        self.outcome = None
        self.render()
        if self.logs_dir:
            self.start_worker()
        self.show_status()

    def stop(self):
        self.stop_worker()
        self.root.after_cancel(self.poll_id)

    # ---- worker ----

    def start_worker(self):
        self.stop_event = threading.Event()
        self.scan_now = threading.Event()
        self.results = queue.Queue()
        threading.Thread(target=scan_worker, daemon=True,
                         args=(self.logs_dir, self.stop_event, self.scan_now, self.results)).start()
        self.check_button.state(["disabled"])

    def stop_worker(self):
        if self.stop_event is not None:
            self.stop_event.set()
            self.scan_now.set()
        self.stop_event = self.scan_now = self.results = None
        self.check_button.state(["disabled"])

    def check_now(self):
        if self.scan_now is not None:
            self.check_button.state(["disabled"])
            self.scan_now.set()

    def poll(self):
        self.poll_id = self.root.after(POLL_MS, self.poll)
        newest = last = None
        while self.results is not None:
            try:
                last = self.results.get_nowait()
            except queue.Empty:
                break
            if last[0] != "scanning":
                newest = last
        if last is None:
            return
        if newest is not None:
            self.apply_result(newest)
        self.check_button.state(["disabled"] if last[0] == "scanning" else ["!disabled"])

    def apply_result(self, item):
        if item[0] == "ok":
            _, self.laps, total, reread, unreadable = item
            self.outcome = ("ok", datetime.now(), total, reread, unreadable)
        else:
            self.outcome = ("error", item[1], item[2])
        self.render()
        self.show_status()

    # ---- add and dismiss ----

    def selected_rows(self):
        return [self.row_by_iid[iid] for iid in self.tree.selection() if iid in self.row_by_iid]

    def add_selected(self):
        rows = self.selected_rows()
        if not rows:
            return
        for row in rows:
            if not row.matched:
                messagebox.showerror(TITLE, "Unmatched rows cannot be added.")
                return
            if row.layout not in self.data.get(row.track, {}):
                messagebox.showerror(
                    TITLE, f"{row.track} / {row.layout} is not in the records file. "
                           "Add the layout to the file first.")
                return
            duplicate = bl.duplicate_message(self.data, row.track, row.layout, row.car,
                                             lbl.format_time(row.ms))
            if duplicate:
                messagebox.showerror(TITLE, duplicate)
                return
        items = []
        for row in rows:
            rec = ask_lap(self.root, row)
            if rec is None:
                return
            items.append((row.track, row.layout, rec))
        if self.add_records(items):
            self.remember(rows, added=True)

    def dismiss_selected(self):
        rows = self.selected_rows()
        if rows:
            self.remember(rows)

    def match_selected(self):
        rows = self.selected_rows()
        if len(rows) != 1:
            messagebox.showerror(TITLE, "Select one row to match.")
            return
        row = rows[0]
        if row.map_track and row.map_car:
            messagebox.showerror(TITLE, "This row is matched by the id map.")
            return
        if not self.catalog_tracks or not self.catalog_cars:
            messagebox.showerror(TITLE, "The catalog (data/tracks.json and data/cars.json) could not be read.")
            return
        picked = ask_match(self.root, row, self.catalog_tracks, self.catalog_cars)
        if picked is None:
            return
        track_layout, car = picked
        track_id, layout_id, car_id = row.ids
        old_matches = copy.deepcopy(self.matches)
        if track_layout:
            self.matches["tracks"].setdefault(track_id, {})[layout_id] = {
                "track": track_layout[0], "layout": track_layout[1]}
        if car:
            self.matches["cars"][car_id] = car
        old_handled = self.handled
        self.handled = bl.migrate_handled(self.handled, self.laps, self.id_map or NO_ID_MAP, self.catalog_tracks,
                                          self.catalog_cars, old_matches, self.matches)
        try:
            bl.write_matches(self.matches)
        except OSError:
            self.matches, self.handled = old_matches, old_handled
            self.status.config(text="Could not save the match.")
        else:
            try:
                bl.write_handled(self.handled)
            except OSError:
                self.status.config(text="The match was saved, but earlier dismissals may reappear after a restart.")
        self.shown = None
        self.render()

    def remember(self, rows, added=False):
        self.handled.extend((row.track, row.layout, row.car, row.ms) + ((True,) if added else ()) for row in rows)
        try:
            bl.write_handled(self.handled)
        except OSError:
            self.status.config(text="Could not save the handled laps; they may reappear after a restart.")
        self.shown = None
        self.render()

    # ---- display ----

    def show_status(self):
        if not self.logs_dir:
            self.status.config(text=NO_FOLDER_MESSAGE)
        elif self.outcome is None:
            self.status.config(text="Best laps: checking...")
        elif self.outcome[0] == "error":
            self.status.config(text=bl.error_message(self.logs_dir, *self.outcome[1:]))
        else:
            _, checked, total, reread, unreadable = self.outcome
            self.status.config(text=bl.ok_message(checked, total, reread, unreadable,
                                                  self.id_map is not None))

    def render(self):
        rows = bl.best_laps(self.laps, self.id_map or NO_ID_MAP, self.catalog_tracks, self.catalog_cars,
                           self.matches)
        rows = [row for row in rows if not bl.is_handled(row, self.handled)]
        items = []
        self.row_by_iid = {}
        for row in rows:
            values = (row.track, row.layout, row.car, row.driver, lbl.format_time(row.ms),
                      bl.marker(row, self.data))
            tags = () if row.matched else ("unmatched",)
            iid = json.dumps([row.track, row.layout, row.car, row.ms])
            self.row_by_iid[iid] = row
            items.append((iid, values, tags))
        if items == self.shown:
            return
        selected = self.tree.selection()
        top = self.tree.yview()[0]
        self.tree.delete(*self.tree.get_children())
        for iid, values, tags in items:
            self.tree.insert("", "end", iid=iid, values=values, tags=tags)
        self.shown = items
        keep = [iid for iid in selected if self.tree.exists(iid)]
        if keep:
            self.tree.selection_set(keep)
        self.tree.yview_moveto(top)
