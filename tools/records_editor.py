"""Tkinter editor for the track records in db/userSetRecords.json."""
import sys
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from check_track_records import CLASSES, is_blank
from records_file import (
    ConflictError,
    RecordsFileError,
    SavedButUnreadableError,
    add,
    build_record,
    delete,
    filter_cars,
    load,
    load_cars,
    load_catalog_cars,
    match_names,
    normalize,
    read_saved_path,
    replace,
    save,
    snap_car,
    write_saved_path,
)

TITLE = "OVRDrive Records Editor"
SAVED_MESSAGE = "Saved. Not live until committed and pushed."
NAVIGATION_KEYS = {"Up", "Down", "Left", "Right", "Home", "End", "Return", "KP_Enter", "Tab",
                   "ISO_Left_Tab", "Escape", "Shift_L", "Shift_R", "Control_L", "Control_R",
                   "Alt_L", "Alt_R", "Caps_Lock"}
SUGGEST_ROWS = 8
COLUMNS = (("class", "Class", 90), ("car", "Car", 220), ("driver", "Driver", 140),
           ("time", "Time", 90), ("year", "Year", 60), ("date", "Date", 90))


def load_with_prompts(path):
    """Load path, asking for another file until one loads. Returns None if cancelled."""
    while True:
        if path:
            try:
                loaded = load(path)
            except RecordsFileError as err:
                messagebox.showerror(TITLE, f"Cannot open {path}:\n{err}")
            else:
                try:
                    write_saved_path(path)
                except OSError:
                    pass
                return loaded
        else:
            messagebox.showinfo(TITLE, "Select the userSetRecords.json file to edit.")
        path = filedialog.askopenfilename(
            title="Select userSetRecords.json",
            filetypes=[("userSetRecords.json", "userSetRecords.json"), ("JSON files", "*.json")],
        )
        if not path:
            return None


class App:
    def __init__(self, root, loaded):
        self.root = root
        self.loaded = loaded
        self.track = None
        self.layout = None
        self.rows = []
        self.editing = None
        self.baseline = None
        self.reformat_confirmed = False
        self.cars = []
        self.catalog_cars = set()

        root.title(TITLE)
        root.minsize(820, 480)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.build_menu()
        self.build_widgets()
        self.apply_loaded(loaded, announce=True)
        self.reset_form()

    # ---- construction ----

    def build_menu(self):
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Change file...", command=self.change_file)
        file_menu.add_command(label="Reload", command=self.reload)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_close)
        menubar.add_cascade(label="File", menu=file_menu)
        self.root.config(menu=menubar)

    def build_widgets(self):
        self.status = tk.StringVar()
        ttk.Label(self.root, textvariable=self.status, anchor="w", relief="sunken").pack(
            side="bottom", fill="x")

        panes = ttk.PanedWindow(self.root, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=6, pady=6)

        left = ttk.Frame(panes)
        panes.add(left, weight=1)
        ttk.Label(left, text="Search").pack(anchor="w")
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self.on_search())
        ttk.Entry(left, textvariable=self.search).pack(fill="x")
        ttk.Label(left, text="Track").pack(anchor="w", pady=(6, 0))
        self.track_list = self.make_listbox(left, 12)
        self.track_list.bind("<<ListboxSelect>>", lambda _e: self.on_track_select())
        ttk.Label(left, text="Layout").pack(anchor="w", pady=(6, 0))
        self.layout_list = self.make_listbox(left, 8)
        self.layout_list.bind("<<ListboxSelect>>", lambda _e: self.on_layout_select())

        notebook = ttk.Notebook(panes)
        panes.add(notebook, weight=3)
        tab = ttk.Frame(notebook, padding=6)
        notebook.add(tab, text="Records")
        self.build_records_tab(tab)

    def make_listbox(self, parent, height):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        box = tk.Listbox(frame, height=height, exportselection=False, width=28)
        bar = ttk.Scrollbar(frame, command=box.yview)
        box.config(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        box.pack(side="left", fill="both", expand=True)
        return box

    def build_records_tab(self, tab):
        self.tree = ttk.Treeview(tab, columns=[c[0] for c in COLUMNS], show="headings",
                                 height=8, selectmode="browse")
        for key, title, width in COLUMNS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True)

        buttons = ttk.Frame(tab)
        buttons.pack(fill="x", pady=6)
        ttk.Button(buttons, text="New", command=self.new_record).pack(side="left")
        ttk.Button(buttons, text="Edit selected", command=self.edit_selected).pack(side="left", padx=6)
        ttk.Button(buttons, text="Delete selected", command=self.delete_selected).pack(side="left")

        form = ttk.LabelFrame(tab, text="Record", padding=6)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        self.cls = tk.StringVar()
        self.car = tk.StringVar()
        self.driver = tk.StringVar()
        self.time = tk.StringVar()
        self.year = tk.StringVar()
        self.date = tk.StringVar()
        for var in (self.cls, self.car, self.driver, self.time, self.year, self.date):
            var.trace_add("write", lambda *_: self.update_dirty_title())

        ttk.Label(form, text="Class").grid(row=0, column=0, sticky="w")
        ttk.Combobox(form, textvariable=self.cls, values=list(CLASSES),
                     state="readonly").grid(row=0, column=1, sticky="ew", pady=2)
        ttk.Label(form, text="Car").grid(row=1, column=0, sticky="w")
        self.car_box = ttk.Combobox(form, textvariable=self.car)
        self.car_box.grid(row=1, column=1, sticky="ew", pady=2)
        self.car_box.bind("<KeyPress>", self.on_car_press)
        self.car_box.bind("<KeyRelease>", self.on_car_key)
        self.car_box.bind("<FocusOut>", lambda _e: self.hide_suggestions())
        self.suggest = tk.Listbox(self.root, height=SUGGEST_ROWS, exportselection=False,
                                  activestyle="none", takefocus=False)
        self.suggest.bind("<Button-1>", self.on_suggest_click)
        self.car_box.bind("<<ComboboxSelected>>", lambda _e: self.show_all_cars())
        ttk.Label(form, text="Driver").grid(row=2, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.driver).grid(row=2, column=1, sticky="ew", pady=2)
        ttk.Label(form, text="Time").grid(row=3, column=0, sticky="w")
        time_row = ttk.Frame(form)
        time_row.grid(row=3, column=1, sticky="ew", pady=2)
        ttk.Entry(time_row, textvariable=self.time, width=14).pack(side="left")
        ttk.Label(time_row, text="m:ss.mmm").pack(side="left", padx=6)
        ttk.Label(form, text="Year").grid(row=4, column=0, sticky="w")
        year_row = ttk.Frame(form)
        year_row.grid(row=4, column=1, sticky="ew", pady=2)
        ttk.Spinbox(year_row, textvariable=self.year, from_=1900, to=date.today().year + 1,
                    width=8).pack(side="left")
        ttk.Label(year_row, text="Year (only the year is saved)").pack(side="left", padx=6)
        ttk.Label(form, text="Date").grid(row=5, column=0, sticky="w")
        date_row = ttk.Frame(form)
        date_row.grid(row=5, column=1, sticky="ew", pady=2)
        ttk.Entry(date_row, textvariable=self.date, width=14).pack(side="left")
        ttk.Label(date_row, text="YYYY-MM-DD, optional").pack(side="left", padx=6)
        ttk.Button(form, text="Save", command=self.save_record).grid(row=6, column=1, sticky="e", pady=(6, 0))

    # ---- state ----

    def form_values(self):
        return (self.cls.get(), self.car.get(), self.driver.get(), self.time.get(), self.year.get(),
                self.date.get())

    def is_dirty(self):
        return self.form_values() != self.baseline

    def update_dirty_title(self):
        if self.baseline is not None:
            self.root.title(TITLE + (" *" if self.is_dirty() else ""))

    def on_car_press(self, event):
        """While suggestions are shown, Down/Up move through them, Return picks, Escape closes."""
        if not self.suggest.winfo_ismapped():
            return None
        if event.keysym in ("Down", "Up"):
            rows = self.suggest.size()
            current = self.suggest.curselection()
            step = 1 if event.keysym == "Down" else -1
            index = min(max((current[0] + step) if current else (0 if step > 0 else rows - 1), 0), rows - 1)
            self.suggest.selection_clear(0, "end")
            self.suggest.selection_set(index)
            self.suggest.see(index)
            return "break"
        if event.keysym in ("Return", "KP_Enter") and self.suggest.curselection():
            self.pick_suggestion(self.suggest.curselection()[0])
            return "break"
        if event.keysym == "Escape":
            self.hide_suggestions()
            return "break"
        return None

    def on_car_key(self, event):
        """Show the cars matching the typed text in a list under the Car field."""
        if event.keysym in NAVIGATION_KEYS:
            return
        matches = match_names(self.cars, self.car.get()) if self.car.get().strip() else []
        self.car_box.config(values=matches or self.cars)
        if not matches:
            self.hide_suggestions()
            return
        self.suggest.delete(0, "end")
        self.suggest.insert("end", *matches)
        self.suggest.config(height=min(len(matches), SUGGEST_ROWS))
        self.suggest.place(x=self.car_box.winfo_rootx() - self.root.winfo_rootx(),
                           y=self.car_box.winfo_rooty() - self.root.winfo_rooty() + self.car_box.winfo_height(),
                           width=self.car_box.winfo_width())
        self.suggest.lift()

    def hide_suggestions(self):
        self.suggest.place_forget()

    def on_suggest_click(self, event):
        index = self.suggest.nearest(event.y)
        if index >= 0:
            self.pick_suggestion(index)
        return "break"

    def pick_suggestion(self, index):
        self.car.set(self.suggest.get(index))
        self.hide_suggestions()
        self.car_box.focus_set()
        self.car_box.icursor("end")

    def show_all_cars(self):
        self.hide_suggestions()
        self.car_box.config(values=self.cars)

    def set_form(self, values):
        for var, value in zip((self.cls, self.car, self.driver, self.time, self.year, self.date), values):
            var.set(value)
        self.show_all_cars()
        self.baseline = self.form_values()
        self.update_dirty_title()

    def default_values(self):
        return ("", "", "", "", str(date.today().year), "")

    def reset_form(self):
        self.editing = None
        self.set_form(self.default_values())

    def confirm_discard(self):
        if not self.is_dirty():
            return True
        return messagebox.askyesno(TITLE, "Discard unsaved changes?")

    def set_status(self, message=""):
        self.status.set(f"{self.loaded.path}    {message}".rstrip())

    # ---- loading ----

    def apply_loaded(self, loaded, announce=False, keep_reformat_confirmed=False):
        self.loaded = loaded
        if not keep_reformat_confirmed:
            self.reformat_confirmed = False
        self.catalog_cars = load_catalog_cars(loaded.path)
        self.cars = load_cars(loaded.path, loaded.data)
        self.show_all_cars()
        self.refresh_tracks()
        message = ""
        if announce and loaded.warnings:
            message = f"{len(loaded.warnings)} warning(s) on load."
            messagebox.showwarning(TITLE, "\n".join(loaded.warnings))
        self.set_status(message)

    def change_file(self):
        if not self.confirm_discard():
            return
        path = filedialog.askopenfilename(
            title="Select userSetRecords.json",
            filetypes=[("userSetRecords.json", "userSetRecords.json"), ("JSON files", "*.json")],
        )
        if not path:
            return
        loaded = load_with_prompts(path)
        if loaded is not None:
            self.reset_selection()
            self.apply_loaded(loaded, announce=True)

    def reload(self):
        if not self.confirm_discard():
            return
        self.reload_from_disk()

    def reload_from_disk(self):
        try:
            loaded = load(self.loaded.path)
        except RecordsFileError as err:
            messagebox.showerror(TITLE, str(err))
            return
        self.reset_form()
        self.apply_loaded(loaded, announce=True)

    def reset_selection(self):
        self.track = None
        self.layout = None
        self.reset_form()

    # ---- left pane ----

    def shown_tracks(self):
        query = self.search.get()
        return [track for track, layouts in self.loaded.data.items()
                if not normalize(query) or match_names([track, *layouts], query)]

    def refresh_tracks(self):
        tracks = self.shown_tracks()
        self.track_list.delete(0, "end")
        for track in tracks:
            self.track_list.insert("end", track)
        keep = self.track
        self.track = None
        self.layout_list.delete(0, "end")
        self.show_records()
        if keep in tracks:
            self.select_track(keep, self.layout)

    def select_track(self, track, layout=None):
        names = self.track_list.get(0, "end")
        index = names.index(track)
        self.track_list.selection_clear(0, "end")
        self.track_list.selection_set(index)
        self.track_list.see(index)
        self.track = track
        self.fill_layouts(layout)

    def fill_layouts(self, layout=None):
        layouts = list(self.loaded.data.get(self.track, {}))
        self.layout_list.delete(0, "end")
        for name in layouts:
            self.layout_list.insert("end", name)
        self.layout = None
        if layout not in layouts and len(layouts) == 1:
            layout = layouts[0]
        if layout in layouts:
            index = layouts.index(layout)
            self.layout_list.selection_set(index)
            self.layout_list.see(index)
            self.layout = layout
        self.show_records()

    def on_search(self):
        if self.track is not None and self.track not in self.shown_tracks():
            self.detach_edit()
        self.refresh_tracks()

    def detach_edit(self):
        """An edited record belongs to its own layout; leaving it makes the form a new, unsaved entry."""
        if self.editing is not None:
            self.editing = None
            self.baseline = self.default_values()
            self.update_dirty_title()

    def on_track_select(self):
        picked = self.track_list.curselection()
        if not picked:
            return
        self.hide_suggestions()
        track = self.track_list.get(picked[0])
        if track == self.track:
            return
        self.detach_edit()
        self.track = track
        self.fill_layouts()

    def on_layout_select(self):
        picked = self.layout_list.curselection()
        if not picked:
            return
        self.hide_suggestions()
        layout = self.layout_list.get(picked[0])
        if layout == self.layout:
            return
        self.detach_edit()
        self.layout = layout
        self.show_records()

    # ---- records table ----

    def show_records(self):
        self.tree.delete(*self.tree.get_children())
        self.rows = []
        if self.track is None or self.layout is None:
            return
        entry = self.loaded.data.get(self.track, {}).get(self.layout)
        if entry is None:
            return
        for rec in entry["records"]:
            if is_blank(rec):
                continue
            self.tree.insert("", "end", iid=str(len(self.rows)),
                             values=[rec.get(key, "") for key, _t, _w in COLUMNS])
            self.rows.append(rec)

    def selected_record(self):
        picked = self.tree.selection()
        return self.rows[int(picked[0])] if picked else None

    def need_layout(self):
        if self.track is None or self.layout is None:
            messagebox.showinfo(TITLE, "Select a track and a layout first.")
            return False
        return True

    # ---- actions ----

    def new_record(self):
        if not self.need_layout() or not self.confirm_discard():
            return
        self.tree.selection_remove(self.tree.selection())
        self.reset_form()

    def edit_selected(self):
        if not self.need_layout():
            return
        rec = self.selected_record()
        if rec is None:
            messagebox.showinfo(TITLE, "Select a record first.")
            return
        if not self.confirm_discard():
            return
        self.editing = rec
        self.set_form((rec.get("class", ""), rec.get("car", ""), rec.get("driver", ""),
                       rec.get("time", ""), str(rec.get("year", "")), str(rec.get("date", ""))))

    def delete_selected(self):
        if not self.need_layout():
            return
        rec = self.selected_record()
        if rec is None:
            messagebox.showinfo(TITLE, "Select a record first.")
            return
        if not self.confirm_discard():
            return
        if not messagebox.askyesno(TITLE, f"Delete the record for {rec.get('driver', '')} "
                                          f"({rec.get('time', '')})?"):
            return
        track, layout = self.track, self.layout
        self.write(lambda data: delete(data, track, layout, rec))

    def save_record(self):
        self.hide_suggestions()
        if not self.need_layout():
            return
        base = self.editing
        self.car.set(snap_car(self.catalog_cars, self.car.get()))
        try:
            rec = build_record(*self.form_values(), base=base)
        except RecordsFileError as err:
            messagebox.showerror(TITLE, str(err))
            return
        if rec["car"] not in self.catalog_cars and not messagebox.askyesno(
                TITLE, "Car not in the catalog. Save anyway?"):
            return
        track, layout = self.track, self.layout
        if base is None:
            self.write(lambda data: add(data, track, layout, rec))
        else:
            self.write(lambda data: replace(data, track, layout, base, rec))

    def write(self, apply):
        if self.loaded.reformats and not self.reformat_confirmed:
            if not messagebox.askokcancel(
                    TITLE, "Saving will reformat the file; review the diff before committing. Continue?"):
                return
            self.reformat_confirmed = True
        try:
            loaded = save(self.loaded.path, apply)
        except ConflictError as err:
            messagebox.showerror(TITLE, str(err))
            self.reload_from_disk()
            return
        except SavedButUnreadableError as err:
            messagebox.showerror(TITLE, str(err))
            self.reset_form()
            self.reload_from_disk()
            return
        except RecordsFileError as err:
            messagebox.showerror(TITLE, str(err))
            return
        self.reset_form()
        self.apply_loaded(loaded, keep_reformat_confirmed=True)
        self.set_status(SAVED_MESSAGE)

    def on_close(self):
        self.hide_suggestions()
        if self.confirm_discard():
            self.root.destroy()


def set_window_icon(root):
    icon = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "records_editor.ico"
    try:
        root.iconbitmap(str(icon))
    except tk.TclError:
        pass


def main():
    root = tk.Tk()
    root.withdraw()
    set_window_icon(root)
    loaded = load_with_prompts(read_saved_path())
    if loaded is None:
        root.destroy()
        return
    App(root, loaded)
    root.deiconify()
    root.mainloop()


if __name__ == "__main__":
    main()
