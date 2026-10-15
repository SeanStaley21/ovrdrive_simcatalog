"""The read-only Best Laps tab: a background scan of the AC server logs shown next to the records."""
import json
import queue
import threading
from datetime import datetime
from tkinter import ttk

import best_laps as bl
import log_best_laps as lbl
from records_file import load_catalog_cars

POLL_MS = 500
NO_FOLDER_MESSAGE = "Best laps: no logs folder set (File > Set logs folder...)"
COLUMNS = (("track", "Track", 180), ("layout", "Layout", 160), ("car", "Car", 200),
           ("driver", "Pod/Driver", 100), ("time", "Time", 90), ("status", "Status", 220))
NO_ID_MAP = {"tracks": {}, "cars": {}}


def scan_worker(logs_dir, stop_event, scan_now, results):
    """Post "scanning", scan, post the outcome, then wait for the interval or a Check now."""
    cache = {}
    while not stop_event.is_set():
        results.put(("scanning",))
        try:
            laps, files, unreadable = bl.scan(logs_dir, cache)
            results.put(("ok", laps, files, unreadable))
        except bl.LogsFolderError as exc:
            results.put(("error", str(exc)))
        except Exception as exc:
            results.put(("error", f"scan failed ({type(exc).__name__})"))
        scan_now.wait(bl.INTERVAL)
        scan_now.clear()


class BestLapsTab:
    def __init__(self, root, notebook):
        self.root = root
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
        self.status.pack(side="bottom", fill="x", before=notebook.master)

        frame = ttk.Frame(notebook, padding=6)
        notebook.add(frame, text="Best Laps")
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(0, 6))
        self.check_button = ttk.Button(buttons, text="Check now", command=self.check_now,
                                       state="disabled")
        self.check_button.pack(side="left")
        table = ttk.Frame(frame)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=[c[0] for c in COLUMNS], show="headings",
                                 height=8, selectmode="browse")
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
        self.catalog_tracks = bl.load_catalog_tracks(loaded.path)
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
            _, self.laps, files, unreadable = item
            self.outcome = ("ok", datetime.now(), files, unreadable)
        else:
            self.outcome = ("error", item[1])
        self.render()
        self.show_status()

    # ---- display ----

    def show_status(self):
        if not self.logs_dir:
            self.status.config(text=NO_FOLDER_MESSAGE)
        elif self.outcome is None:
            self.status.config(text="Best laps: checking...")
        elif self.outcome[0] == "error":
            self.status.config(text=bl.error_message(self.logs_dir, self.outcome[1]))
        else:
            _, checked, files, unreadable = self.outcome
            self.status.config(text=bl.ok_message(checked, files, unreadable, self.id_map is not None))

    def render(self):
        rows = bl.best_laps(self.laps, self.id_map or NO_ID_MAP, self.catalog_tracks, self.catalog_cars)
        items = []
        for row in rows:
            values = (row.track, row.layout, row.car, row.driver, lbl.format_time(row.ms),
                      bl.marker(row, self.data))
            tags = () if row.matched else ("unmatched",)
            items.append((json.dumps([row.track, row.layout, row.car]), values, tags))
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
