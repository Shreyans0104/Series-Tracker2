#!/usr/bin/env python3
"""
Series Tracker - dark blue/black interface.

First time only:   pip install customtkinter
Run:               python gui.py        (keep it next to tracker.py)

Design notes
  * True black (#000000) background: on OLED/AMOLED screens black pixels are switched off.
  * No animations and no background polling while idle, so the app uses almost no CPU.
  * Same data, buttons and CSV export as before - only the look changed.
"""
import queue
import threading
import tkinter as tk
from tkinter import ttk

try:
    import customtkinter as ctk
except ImportError:  # friendly message instead of a crash (works even without a console)
    from tkinter import messagebox
    _r = tk.Tk()
    _r.withdraw()
    messagebox.showerror("One package is missing",
                         "Install the interface package first.\n\nOpen a terminal and run:\n\n"
                         "pip install customtkinter")
    raise SystemExit

import tracker

# ---------------------------------------------------------------- theme ----
BLACK = "#000000"        # window background (pixels off on OLED)
INK = "#060A14"          # panels
RAISED = "#0C1426"       # inputs, season cards
LINE = "#17233F"         # borders, empty bars
ACCENT = "#2F6BFF"       # primary blue
ACCENT_HOVER = "#4D84FF"
ACCENT_SOFT = "#0F2250"  # selected row
SKY = "#7FB2FF"          # light blue text / numbers
TEXT = "#E6ECFF"
MUTED = "#7F8DB0"
AMBER = "#F5C26B"
DANGER = "#FF6B7A"
FONT = "Segoe UI"

STATUS_FG = {"Completed": SKY, "In progress": AMBER, "Not started": MUTED, "Not watched": MUTED}
STATUS_BG = {"Completed": "#0E2A5C", "In progress": "#33260B", "Not started": "#121A2E",
             "Not watched": "#121A2E"}
COMMON_LANGS = ["Hindi", "English", "Marathi", "Tamil", "Telugu", "Malayalam",
                "Korean", "Japanese", "Spanish", "French", "German"]

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


# ----------------------------------------------------------- small parts ---
def entry(master, **kw):
    return ctk.CTkEntry(master, fg_color=RAISED, border_color=LINE, text_color=TEXT,
                        placeholder_text_color=MUTED, height=38, corner_radius=10, **kw)


def combo(master, values, **kw):
    return ctk.CTkComboBox(master, values=values, fg_color=RAISED, border_color=LINE,
                           button_color=LINE, button_hover_color=ACCENT, text_color=TEXT,
                           dropdown_fg_color=INK, dropdown_hover_color=ACCENT_SOFT,
                           dropdown_text_color=TEXT, height=38, corner_radius=10, **kw)


def primary_btn(master, text, command, **kw):
    kw.setdefault("height", 38)
    return ctk.CTkButton(master, text=text, command=command, fg_color=ACCENT,
                         hover_color=ACCENT_HOVER, text_color="#FFFFFF",
                         corner_radius=10, **kw)


def ghost_btn(master, text, command, color=TEXT, border=LINE, **kw):
    kw.setdefault("height", 38)
    return ctk.CTkButton(master, text=text, command=command, fg_color="transparent",
                         hover_color=LINE, border_width=1, border_color=border,
                         text_color=color, corner_radius=10, **kw)


class Stepper(ctk.CTkFrame):
    """A - 3 + control for whole numbers."""

    def __init__(self, master, value, minimum, maximum, font):
        super().__init__(master, fg_color="transparent")
        self.minimum, self.maximum = minimum, maximum
        self.value = max(minimum, min(maximum, value))
        for sign, delta, side in (("-", -1, "left"), ("+", 1, "right")):
            btn = ctk.CTkButton(self, text=sign, width=36, height=36, corner_radius=10,
                                fg_color=RAISED, hover_color=LINE, text_color=TEXT,
                                command=lambda d=delta: self.step(d))
            btn.pack(side=side)
        self.label = ctk.CTkLabel(self, text=str(self.value), width=52, font=font, text_color=TEXT)
        self.label.pack(side="left")

    def step(self, delta):
        self.set(self.value + delta)

    def set(self, value):
        self.value = max(self.minimum, min(self.maximum, value))
        self.label.configure(text=str(self.value))

    def get(self):
        return self.value


class Modal(ctk.CTkToplevel):
    def __init__(self, app, title, width, height):
        super().__init__(app, fg_color=INK)
        self.app = app
        self.title(title)
        self.resizable(False, False)
        self.transient(app)
        x = app.winfo_x() + max((app.winfo_width() - width) // 2, 0)
        y = app.winfo_y() + max((app.winfo_height() - height) // 3, 0)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.after(200, self._finish)

    def _finish(self):
        try:
            self.iconbitmap(str(tracker.BASE / "series.ico"))
            self.lift()
            self.focus_force()
            self.grab_set()
        except tk.TclError:
            pass

    def label(self, text, font=None, color=TEXT, **kw):
        return ctk.CTkLabel(self, text=text, font=font or self.app.f["body"], text_color=color,
                            anchor="w", **kw)


class Confirm(Modal):
    def __init__(self, app, title, message, ok_text, danger=False):
        super().__init__(app, title, 440, 210)
        self.result = False
        self.label(title, self.app.f["h2"]).pack(fill="x", padx=24, pady=(22, 6))
        self.label(message, color=MUTED, wraplength=390, justify="left").pack(fill="x", padx=24)
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(side="bottom", fill="x", padx=24, pady=20)
        ok = ctk.CTkButton(row, text=ok_text, height=38, corner_radius=10, width=120,
                           fg_color=DANGER if danger else ACCENT,
                           hover_color="#FF8591" if danger else ACCENT_HOVER,
                           text_color="#000000" if danger else "#FFFFFF",
                           command=lambda: self.choose(True))
        ok.pack(side="right")
        ghost_btn(row, "Cancel", lambda: self.choose(False), width=100).pack(side="right", padx=8)

    def choose(self, value):
        self.result = value
        self.destroy()


class Notice(Modal):
    def __init__(self, app, title, message):
        lines = message.count("\n") + 1
        super().__init__(app, title, 520, min(150 + lines * 24, 460))
        self.label(title, self.app.f["h2"]).pack(fill="x", padx=24, pady=(22, 8))
        box = ctk.CTkTextbox(self, fg_color=RAISED, text_color=TEXT, border_width=0,
                             corner_radius=10, font=self.app.f["body"], wrap="word")
        box.pack(fill="both", expand=True, padx=24)
        box.insert("1.0", message)
        box.configure(state="disabled")
        primary_btn(self, "Done", self.destroy, width=100).pack(side="right", padx=24, pady=16)


class AddDialog(Modal):
    def __init__(self, app):
        super().__init__(app, "Add series", 560, 640)
        self.results, self.picked, self.rows = [], None, []
        self.label("Add a series", self.app.f["h2"]).pack(fill="x", padx=24, pady=(22, 2))
        self.label("Search by name, then choose the right match.", color=MUTED).pack(fill="x", padx=24)

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=24, pady=(14, 8))
        self.query = entry(bar, placeholder_text="e.g. Breaking Bad")
        self.query.pack(side="left", fill="x", expand=True)
        self.query.bind("<Return>", lambda e: self.search())
        primary_btn(bar, "Search", self.search, width=90).pack(side="left", padx=(8, 0))

        self.results_box = ctk.CTkScrollableFrame(self, fg_color=BLACK, corner_radius=12, height=190,
                                                  scrollbar_button_color=LINE,
                                                  scrollbar_button_hover_color=ACCENT)
        self.results_box.pack(fill="x", padx=24)
        self.hint = ctk.CTkLabel(self.results_box, text="Results appear here.", text_color=MUTED,
                                 font=self.app.f["body"])
        self.hint.pack(pady=40)

        self.label("What have you watched? (optional)", self.app.f["h3"]).pack(fill="x", padx=24, pady=(16, 6))
        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(fill="x", padx=24)
        form.columnconfigure(1, weight=1)
        ctk.CTkLabel(form, text="Seasons", text_color=MUTED, anchor="w").grid(row=0, column=0, sticky="w", pady=4)
        self.spec = entry(form, placeholder_text="all, none, or 1-3,5")
        self.spec.grid(row=0, column=1, sticky="ew", padx=(14, 0), pady=4)
        ctk.CTkLabel(form, text="Times watched", text_color=MUTED, anchor="w").grid(row=1, column=0, sticky="w", pady=4)
        self.times = Stepper(form, 1, 1, 99, self.app.f["h3"])
        self.times.grid(row=1, column=1, sticky="w", padx=(14, 0), pady=4)
        ctk.CTkLabel(form, text="Watched in", text_color=MUTED, anchor="w").grid(row=2, column=0, sticky="w", pady=4)
        self.lang = combo(form, [""] + COMMON_LANGS)
        self.lang.set("")
        self.lang.grid(row=2, column=1, sticky="ew", padx=(14, 0), pady=4)

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(side="bottom", fill="x", padx=24, pady=18)
        primary_btn(row, "Add series", self.add, width=130).pack(side="right")
        ghost_btn(row, "Cancel", self.destroy, width=100).pack(side="right", padx=8)
        self.after(250, self.query.focus_set)

    def search(self):
        q = self.query.get().strip()
        if not q:
            return

        def work():
            return tracker.tmdb("/search/tv", query=q).get("results", [])[:8]

        def done(results):
            if not self.winfo_exists():
                return
            self.app.set_status("Ready")
            self.results, self.picked = results, None
            for w in self.results_box.winfo_children():
                w.destroy()
            self.rows = []
            if not results:
                ctk.CTkLabel(self.results_box, text="No matches. Check the spelling or try fewer words.",
                             text_color=MUTED).pack(pady=40)
                return
            for i, r in enumerate(results):
                year = (r.get("first_air_date") or "")[:4]
                lang = tracker.LANG_FALLBACK.get(r.get("original_language"), r.get("original_language") or "")
                btn = ctk.CTkButton(self.results_box, text=f"{r['name']}   {year}   {lang}", anchor="w",
                                    fg_color="transparent", hover_color=LINE, text_color=TEXT, height=36,
                                    corner_radius=8, command=lambda i=i: self.pick(i))
                btn.pack(fill="x", pady=1)
                self.rows.append(btn)
            self.pick(0)

        self.app.run_bg(work, done, "Searching...")

    def pick(self, i):
        self.picked = i
        for j, btn in enumerate(self.rows):
            btn.configure(fg_color=ACCENT_SOFT if j == i else "transparent",
                          text_color=SKY if j == i else TEXT)

    def add(self):
        if self.picked is None:
            return self.app.notice("Choose a series", "Search for a name and click the match you want.")
        tv_id = self.results[self.picked]["id"]
        spec = self.spec.get().strip() or "none"
        lang = self.lang.get().strip() or None
        times = self.times.get()

        def work():
            conn = tracker.connect()
            try:
                series, seasons = tracker.fetch_series(tv_id)
                tracker.save_series(conn, series, seasons)
                if spec.lower() != "none":
                    tracker.mark_watched(conn, tv_id, spec, times, None, lang)
                tracker.export_csv(conn)
                return series["name"], len(seasons)
            finally:
                conn.close()

        def done(result):
            name, n = result
            self.app.selected_id = tv_id
            self.app.refresh(select=tv_id)
            self.app.set_status(f"Added {name} with {n} seasons")
            if self.winfo_exists():
                self.destroy()

        self.app.run_bg(work, done, "Fetching details...")


class MarkDialog(Modal):
    def __init__(self, app):
        super().__init__(app, "Mark seasons watched", 440, 360)
        self.label("Mark seasons watched", self.app.f["h2"]).pack(fill="x", padx=24, pady=(22, 12))
        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(fill="x", padx=24)
        form.columnconfigure(1, weight=1)
        ctk.CTkLabel(form, text="Seasons", text_color=MUTED).grid(row=0, column=0, sticky="w", pady=6)
        self.spec = entry(form, placeholder_text="all, 3, or 1-3,5")
        self.spec.insert(0, "all")
        self.spec.grid(row=0, column=1, sticky="ew", padx=(14, 0))
        ctk.CTkLabel(form, text="Times watched", text_color=MUTED).grid(row=1, column=0, sticky="w", pady=6)
        self.times = Stepper(form, 1, 1, 99, self.app.f["h3"])
        self.times.grid(row=1, column=1, sticky="w", padx=(14, 0))
        ctk.CTkLabel(form, text="Watched in", text_color=MUTED).grid(row=2, column=0, sticky="w", pady=6)
        self.lang = combo(form, app.series_languages())
        self.lang.set("")
        self.lang.grid(row=2, column=1, sticky="ew", padx=(14, 0))
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(side="bottom", fill="x", padx=24, pady=18)
        primary_btn(row, "Save", self.save, width=100).pack(side="right")
        ghost_btn(row, "Cancel", self.destroy, width=100).pack(side="right", padx=8)

    def save(self):
        self.app.apply_watch(self.spec.get(), self.times.get(), None, self.lang.get().strip())
        self.destroy()


class SeasonDialog(Modal):
    def __init__(self, app, season_no, data):
        super().__init__(app, f"Season {season_no}", 440, 380)
        self.n, self.total = season_no, data[1]
        self.label(f"Season {season_no}", self.app.f["h2"]).pack(fill="x", padx=24, pady=(22, 12))
        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(fill="x", padx=24)
        form.columnconfigure(1, weight=1)
        ctk.CTkLabel(form, text=f"Episodes seen (of {self.total})", text_color=MUTED).grid(
            row=0, column=0, sticky="w", pady=6)
        box = ctk.CTkFrame(form, fg_color="transparent")
        box.grid(row=0, column=1, sticky="w", padx=(14, 0))
        self.eps = Stepper(box, data[2], 0, self.total, self.app.f["h3"])
        self.eps.pack(side="left")
        ghost_btn(box, "All", lambda: self.eps.set(self.total), width=50, height=36).pack(side="left", padx=8)
        ctk.CTkLabel(form, text="Times watched", text_color=MUTED).grid(row=1, column=0, sticky="w", pady=6)
        self.times = Stepper(form, data[3] or 1, 1, 99, self.app.f["h3"])
        self.times.grid(row=1, column=1, sticky="w", padx=(14, 0))
        ctk.CTkLabel(form, text="Watched in", text_color=MUTED).grid(row=2, column=0, sticky="w", pady=6)
        self.lang = combo(form, app.series_languages())
        self.lang.set(data[4] or "")
        self.lang.grid(row=2, column=1, sticky="ew", padx=(14, 0))
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(side="bottom", fill="x", padx=24, pady=18)
        primary_btn(row, "Save", self.save, width=100).pack(side="right")
        ghost_btn(row, "Cancel", self.destroy, width=100).pack(side="right", padx=8)

    def save(self):
        self.app.set_season(self.n, self.eps.get(), self.times.get(), self.lang.get().strip())
        self.destroy()


# ------------------------------------------------------------------ app ----
class App(ctk.CTk):
    COLUMNS = [("Series", 250, "w"), ("Language", 90, "w"), ("Seasons", 70, "e"),
               ("Episodes", 75, "e"), ("Hours", 70, "e"), ("Done", 65, "e"),
               ("Times", 55, "e"), ("Status", 100, "w")]

    def __init__(self):
        super().__init__(fg_color=BLACK)
        self.title("Series Tracker")
        self.geometry("1300x800")
        self.minsize(1050, 660)
        self.after(250, self._set_icon)
        self.f = {
            "hero": ctk.CTkFont(family=FONT, size=58, weight="bold"),
            "h1": ctk.CTkFont(family=FONT, size=26, weight="bold"),
            "h2": ctk.CTkFont(family=FONT, size=18, weight="bold"),
            "h3": ctk.CTkFont(family=FONT, size=14, weight="bold"),
            "body": ctk.CTkFont(family=FONT, size=13),
            "small": ctk.CTkFont(family=FONT, size=12),
            "stat": ctk.CTkFont(family=FONT, size=30, weight="bold"),
        }
        self.q = queue.Queue()
        self.pending, self.polling = 0, False
        self.selected_id, self.season_data = None, {}
        self.all_rows = []
        self.sort_idx, self.sort_rev = 1, False
        self.status_filter = "All"
        self._silent = False
        self._style_tree()
        self._build()
        self.refresh()

    def _set_icon(self):
        try:
            self.iconbitmap(str(tracker.BASE / "series.ico"))
        except tk.TclError:
            pass

    def _style_tree(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        s.configure("Treeview", background=INK, fieldbackground=INK, foreground=TEXT,
                    borderwidth=0, rowheight=38, font=(FONT, 11))
        s.map("Treeview", background=[("selected", ACCENT_SOFT)], foreground=[("selected", "#FFFFFF")])
        s.configure("Treeview.Heading", background=INK, foreground=MUTED, borderwidth=0,
                    relief="flat", padding=(10, 10), font=(FONT, 10, "bold"))
        s.map("Treeview.Heading", background=[("active", RAISED)], foreground=[("active", TEXT)])

    # ---------------------------------------------------------- layout ----
    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # header
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=28, pady=(22, 0))
        logo = ctk.CTkLabel(head, text="▶", width=40, height=40, corner_radius=12, fg_color=ACCENT,
                            text_color="#FFFFFF", font=self.f["h3"])
        logo.pack(side="left")
        ctk.CTkLabel(head, text="Series Tracker", font=self.f["h2"], text_color=TEXT).pack(side="left", padx=12)
        primary_btn(head, "+ Add series", self.open_add, width=130).pack(side="right")
        ghost_btn(head, "Export CSVs", self.export_now, width=110).pack(side="right", padx=8)
        ghost_btn(head, "Check for new seasons", self.check_updates, width=170).pack(side="right")

        # stats
        stats = ctk.CTkFrame(self, fg_color="transparent")
        stats.grid(row=1, column=0, sticky="ew", padx=28, pady=(22, 14))
        hero = ctk.CTkFrame(stats, fg_color="transparent")
        hero.pack(side="left")
        self.hero_num = ctk.CTkLabel(hero, text="0", font=self.f["hero"], text_color=SKY, anchor="w")
        self.hero_num.pack(anchor="w")
        ctk.CTkLabel(hero, text="hours watched, rewatches included", font=self.f["small"],
                     text_color=MUTED, anchor="w").pack(anchor="w")
        self.stat_labels = {}
        for key, caption in (("series", "series tracked"), ("completed", "completed"),
                             ("progress", "in progress")):
            box = ctk.CTkFrame(stats, fg_color="transparent")
            box.pack(side="right", padx=(34, 0))
            num = ctk.CTkLabel(box, text="0", font=self.f["stat"], text_color=TEXT, anchor="e")
            num.pack(anchor="e")
            ctk.CTkLabel(box, text=caption, font=self.f["small"], text_color=MUTED, anchor="e").pack(anchor="e")
            self.stat_labels[key] = num

        # main area
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=2, column=0, sticky="nsew", padx=28, pady=(0, 6))
        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=2, minsize=400)
        main.rowconfigure(0, weight=1)

        left = ctk.CTkFrame(main, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)
        tools = ctk.CTkFrame(left, fg_color="transparent")
        tools.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.seg = ctk.CTkSegmentedButton(tools, values=["All", "Completed", "In progress", "Not started"],
                                          command=self.set_filter, fg_color=INK, selected_color=ACCENT,
                                          selected_hover_color=ACCENT_HOVER, unselected_color=INK,
                                          unselected_hover_color=LINE, text_color=TEXT, height=36,
                                          corner_radius=10, font=self.f["small"])
        self.seg.set("All")
        self.seg.pack(side="left")
        self.search = entry(tools, placeholder_text="Search your series", width=240)
        self.search.pack(side="right")
        self.search.bind("<KeyRelease>", lambda e: self.render_rows())

        self.table = ctk.CTkFrame(left, fg_color=INK, corner_radius=16, border_width=1, border_color=LINE)
        self.table.grid(row=1, column=0, sticky="nsew")
        self.tree = ttk.Treeview(self.table, columns=[c[0] for c in self.COLUMNS], show="headings",
                                 selectmode="browse")
        for i, (name, width, anchor) in enumerate(self.COLUMNS):
            self.tree.heading(name, text=name, command=lambda i=i: self.sort_by(i + 1))
            self.tree.column(name, width=width, anchor=anchor, stretch=(name == "Series"))
        scroll = ctk.CTkScrollbar(self.table, command=self.tree.yview, button_color=LINE,
                                  button_hover_color=ACCENT, fg_color=INK)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y", padx=(0, 4), pady=10)
        self.tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=10)
        for status, color in STATUS_FG.items():
            self.tree.tag_configure(status, foreground=color)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.bind("<Delete>", lambda e: self.delete_selected())
        self.empty = ctk.CTkLabel(self.table, text="No series yet.\nClick + Add series to start your list.",
                                  font=self.f["body"], text_color=MUTED, justify="center")

        self.detail = ctk.CTkFrame(main, fg_color=INK, corner_radius=16, border_width=1, border_color=LINE)
        self.detail.grid(row=0, column=1, sticky="nsew")

        self.status = ctk.CTkLabel(self, text="Ready", font=self.f["small"], text_color=MUTED, anchor="w")
        self.status.grid(row=3, column=0, sticky="ew", padx=30, pady=(2, 10))

    def set_status(self, text):
        self.status.configure(text=text)

    # ------------------------------------------------- background tasks ----
    def run_bg(self, fn, done, message):
        self.set_status(message)
        self.pending += 1

        def worker():
            try:
                res = ("ok", fn())
            except (Exception, SystemExit) as e:
                res = ("err", e)
            self.q.put((done, res))

        threading.Thread(target=worker, daemon=True).start()
        if not self.polling:  # poll only while something is running, so the idle app does nothing
            self.polling = True
            self.after(120, self._poll)

    def _poll(self):
        try:
            while True:
                done, (kind, val) = self.q.get_nowait()
                self.pending -= 1
                try:
                    if kind == "ok":
                        done(val)
                    else:
                        self.set_status("Ready")
                        self.notice("Something went wrong", str(val) or repr(val))
                except tk.TclError:
                    pass  # the dialog that asked for this was closed meanwhile
                except Exception as e:
                    self.set_status("Ready")
                    self.notice("Something went wrong", str(e))
        except queue.Empty:
            pass
        if self.pending > 0:
            self.after(120, self._poll)
        else:
            self.polling = False

    def notice(self, title, message):
        Notice(self, title, message)

    def safe(self, fn):
        try:
            return fn()
        except Exception as e:
            self.notice("Something went wrong", str(e))

    # ------------------------------------------------------- data views ----
    def load_rows(self):
        conn = tracker.connect()
        try:
            self.all_rows = conn.execute("""
                SELECT sr.series_id, sr.name, COALESCE(sr.original_language,''),
                       COALESCE(s.total_seasons,0), COALESCE(s.total_episodes,0),
                       ROUND(COALESCE(s.total_minutes,0)/60.0,1), COALESCE(s.completion_pct,0),
                       COALESCE(s.times_watched,0), COALESCE(s.watch_status,'Not started'),
                       COALESCE(s.minutes_watched_incl_rewatch,0)
                FROM series sr LEFT JOIN series_summary s ON s.series_id = sr.series_id
            """).fetchall()
        finally:
            conn.close()

    def refresh(self, select=None):
        self.load_rows()
        if select is not None:
            self.selected_id = select
        self.render_rows()
        self.show_detail()
        self.set_status("Ready")

    def render_rows(self):
        text = self.search.get().strip().lower()
        shown = [r for r in self.all_rows if text in r[1].lower()
                 and (self.status_filter == "All" or r[8] == self.status_filter)]
        idx = self.sort_idx
        shown.sort(key=lambda r: r[idx].lower() if isinstance(r[idx], str) else r[idx], reverse=self.sort_rev)

        for i, (name, _, _) in enumerate(self.COLUMNS):
            arrow = (" ▼" if self.sort_rev else " ▲") if i + 1 == idx else ""
            self.tree.heading(name, text=name + arrow)

        self._silent = True
        self.tree.delete(*self.tree.get_children())
        for r in shown:
            self.tree.insert("", "end", iid=str(r[0]), tags=(r[8],),
                             values=(r[1], r[2], r[3], r[4], f"{r[5]:g}", f"{r[6]:.0f}%", r[7], r[8]))
        if self.selected_id is not None and self.tree.exists(str(self.selected_id)):
            self.tree.selection_set(str(self.selected_id))
            self.tree.see(str(self.selected_id))
        self._silent = False

        if self.all_rows:
            self.empty.place_forget()
        else:
            self.empty.place(relx=0.5, rely=0.5, anchor="center")

        rows = self.all_rows
        self.hero_num.configure(text=f"{sum(r[9] for r in rows) / 60:,.0f}")
        self.stat_labels["series"].configure(text=str(len(rows)))
        self.stat_labels["completed"].configure(text=str(sum(r[8] == "Completed" for r in rows)))
        self.stat_labels["progress"].configure(text=str(sum(r[8] == "In progress" for r in rows)))

    def set_filter(self, value):
        self.status_filter = value
        self.render_rows()

    def sort_by(self, idx):
        self.sort_rev = (not self.sort_rev) if idx == self.sort_idx else False
        self.sort_idx = idx
        self.render_rows()

    def on_select(self, _event=None):
        if self._silent:
            return
        sel = self.tree.selection()
        if sel:
            self.selected_id = int(sel[0])
            self.show_detail()

    # --------------------------------------------------- detail panel ------
    def show_detail(self):
        for w in self.detail.winfo_children():
            w.destroy()
        info, seasons = None, []
        if self.selected_id is not None:
            conn = tracker.connect()
            try:
                info = conn.execute("""
                    SELECT sr.name, sr.original_language, sr.origin_country, sr.genres, sr.status,
                           COALESCE(s.total_seasons,0), COALESCE(s.total_episodes,0),
                           COALESCE(s.total_minutes,0), COALESCE(s.episodes_watched,0),
                           COALESCE(s.completion_pct,0), COALESCE(s.times_watched,0),
                           COALESCE(s.minutes_watched_incl_rewatch,0), COALESCE(s.watch_status,'Not started')
                    FROM series sr LEFT JOIN series_summary s ON s.series_id = sr.series_id
                    WHERE sr.series_id = ?""", (self.selected_id,)).fetchone()
                seasons = conn.execute("""
                    SELECT season_no, episodes, episodes_watched, watch_count, watched_language,
                           season_status, minutes_watched_incl_rewatch
                    FROM season_detail WHERE series_id=? ORDER BY season_no""", (self.selected_id,)).fetchall()
            finally:
                conn.close()
        if not info:
            self.selected_id = None
            self.season_data = {}
            ctk.CTkLabel(self.detail, text="Select a series to see its seasons\nand how far you got.",
                         font=self.f["body"], text_color=MUTED, justify="center").place(
                relx=0.5, rely=0.5, anchor="center")
            return
        self.season_data = {r[0]: r for r in seasons}
        name, lang, country, genres, show_status, n_seasons, n_eps, tot_min, eps_seen, pct, times, min_seen, wstatus = info

        pad = {"padx": 24}
        ctk.CTkLabel(self.detail, text=name, font=self.f["h1"], text_color=TEXT, anchor="w",
                     justify="left", wraplength=360).pack(fill="x", pady=(22, 2), **pad)
        meta = ", ".join(x for x in (lang, country) if x)
        ctk.CTkLabel(self.detail, text=meta or "Language unknown", font=self.f["body"], text_color=SKY,
                     anchor="w").pack(fill="x", **pad)
        ctk.CTkLabel(self.detail, text=f"{genres or 'No genres listed'}   |   {show_status}",
                     font=self.f["small"], text_color=MUTED, anchor="w", wraplength=360,
                     justify="left").pack(fill="x", pady=(2, 14), **pad)

        top = ctk.CTkFrame(self.detail, fg_color="transparent")
        top.pack(fill="x", **pad)
        ctk.CTkLabel(top, text=f"{pct:.0f}%", font=self.f["stat"], text_color=TEXT).pack(side="left")
        ctk.CTkLabel(top, text=f"  {wstatus}  ", font=self.f["small"], height=26, corner_radius=13,
                     fg_color=STATUS_BG.get(wstatus, RAISED), text_color=STATUS_FG.get(wstatus, TEXT)
                     ).pack(side="left", padx=12)
        bar = ctk.CTkProgressBar(self.detail, height=10, corner_radius=5, fg_color=LINE, progress_color=ACCENT)
        bar.set(min(max(pct / 100, 0), 1))
        bar.pack(fill="x", pady=(8, 8), **pad)
        facts = (f"{eps_seen} of {n_eps} episodes seen      {min_seen / 60:,.1f} of "
                 f"{tot_min / 60:,.1f} hours      {times} time{'s' if times != 1 else ''} watched")
        ctk.CTkLabel(self.detail, text=facts, font=self.f["small"], text_color=MUTED, anchor="w",
                     wraplength=360, justify="left").pack(fill="x", **pad)

        acts = ctk.CTkFrame(self.detail, fg_color="transparent")
        acts.pack(fill="x", pady=(16, 6), **pad)
        ghost_btn(acts, "Mark seasons", self.open_mark, height=34, width=110).pack(side="left")
        ghost_btn(acts, "Clear", self.clear_watch, height=34, width=70).pack(side="left", padx=8)
        ghost_btn(acts, "Delete", self.delete_selected, color=DANGER, border="#4A1E26",
                  height=34, width=80).pack(side="right")

        ctk.CTkLabel(self.detail, text="Seasons", font=self.f["h3"], text_color=TEXT, anchor="w").pack(
            fill="x", pady=(12, 4), **pad)
        scroll = ctk.CTkScrollableFrame(self.detail, fg_color="transparent", scrollbar_button_color=LINE,
                                        scrollbar_button_hover_color=ACCENT)
        scroll.pack(fill="both", expand=True, padx=(16, 12), pady=(0, 14))
        for n, eps, seen, count, wlang, status, _mins in seasons:
            card = ctk.CTkFrame(scroll, fg_color=RAISED, corner_radius=12)
            card.pack(fill="x", pady=4)
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=(10, 6))
            ctk.CTkLabel(row, text=f"Season {n}", font=self.f["h3"], text_color=TEXT).pack(side="left")
            ctk.CTkButton(row, text="Edit", width=54, height=26, corner_radius=8, fg_color="transparent",
                          hover_color=LINE, border_width=1, border_color=LINE, text_color=SKY,
                          font=self.f["small"], command=lambda n=n: self.edit_season(n)).pack(side="right")
            color = {"Completed": ACCENT, "In progress": AMBER}.get(status, LINE)
            pb = ctk.CTkProgressBar(card, height=7, corner_radius=4, fg_color=LINE, progress_color=color)
            pb.set(seen / eps if eps else 0)
            pb.pack(fill="x", padx=14)
            note = (f"{seen} of {eps} episodes, watched {count} time{'s' if count != 1 else ''} in {wlang}"
                    if seen else f"{eps} episodes, not watched yet")
            ctk.CTkLabel(card, text=note, font=self.f["small"], text_color=MUTED, anchor="w").pack(
                fill="x", padx=14, pady=(6, 10))

    # ----------------------------------------------------------- actions ---
    def series_languages(self):
        conn = tracker.connect()
        try:
            row = conn.execute("SELECT original_language, spoken_languages FROM series WHERE series_id=?",
                               (self.selected_id,)).fetchone()
        finally:
            conn.close()
        langs = []
        if row:
            langs += [row[0]] + [x.strip() for x in (row[1] or "").split(",")]
        langs += [l for l in COMMON_LANGS if l not in langs]
        return [l for l in dict.fromkeys(langs) if l]

    def open_add(self):
        AddDialog(self)

    def open_mark(self):
        if self.selected_id is None:
            return self.notice("Choose a series", "Select a series in the list first.")
        MarkDialog(self)

    def edit_season(self, n):
        if n in self.season_data:
            SeasonDialog(self, n, self.season_data[n])

    def _write(self, fn):
        def go():
            conn = tracker.connect()
            try:
                fn(conn)
                tracker.export_csv(conn)
            finally:
                conn.close()
        self.safe(go)
        self.refresh()

    def apply_watch(self, spec, times, episodes, lang):
        sid = self.selected_id
        self._write(lambda c: tracker.mark_watched(c, sid, spec, times, episodes, lang or None))

    def set_season(self, n, episodes, times, lang):
        sid = self.selected_id

        def fn(conn):
            if episodes == 0:
                conn.execute("DELETE FROM watch_log WHERE series_id=? AND season_no=?", (sid, n))
                conn.commit()
            else:
                tracker.mark_watched(conn, sid, str(n), max(times, 1), episodes, lang or None)
        self._write(fn)

    def clear_watch(self):
        if self.selected_id is None:
            return
        dlg = Confirm(self, "Clear watch data", "Mark every season of this series as not watched? "
                      "The series stays in your list.", "Clear")
        self.wait_window(dlg)
        if not dlg.result:
            return
        sid = self.selected_id

        def fn(conn):
            conn.execute("DELETE FROM watch_log WHERE series_id=?", (sid,))
            conn.commit()
        self._write(fn)

    def delete_selected(self):
        if self.selected_id is None:
            return self.notice("Choose a series", "Select the series you want to delete.")
        name = self.tree.item(str(self.selected_id), "values")[0] if self.tree.exists(str(self.selected_id)) else "this series"
        dlg = Confirm(self, "Delete series", f"Delete {name} and all its watch history? This can't be undone.",
                      "Delete", danger=True)
        self.wait_window(dlg)
        if not dlg.result:
            return
        sid = self.selected_id
        self.selected_id = None

        def fn(conn):
            for table in ("watch_log", "seasons", "series"):
                conn.execute(f"DELETE FROM {table} WHERE series_id=?", (sid,))
            conn.commit()
        self._write(fn)

    def export_now(self):
        def go():
            conn = tracker.connect()
            try:
                tracker.export_csv(conn)
            finally:
                conn.close()
        self.safe(go)
        self.set_status(f"CSV files saved to {tracker.EXPORT_DIR}")

    def check_updates(self):
        def work():
            conn = tracker.connect()
            lines = []
            try:
                rows = conn.execute("SELECT series_id, name FROM series "
                                    "WHERE status NOT IN ('Ended','Canceled')").fetchall()
                for sid, name in rows:
                    try:
                        series, seasons = tracker.fetch_series(sid)
                        for kind, n, val in tracker.save_series(conn, series, seasons):
                            if kind == "NEW_SEASON":
                                lines.append(f"New season: {name}, season {n} ({val} episodes)")
                            else:
                                lines.append(f"{name}, season {n}: {val} new episode(s)")
                    except (Exception, SystemExit) as e:
                        lines.append(f"Could not refresh {name}: {e}")
                tracker.export_csv(conn)
                return len(rows), lines
            finally:
                conn.close()

        def done(result):
            count, lines = result
            self.refresh()
            self.notice(f"Checked {count} running series",
                        "\n".join(lines) if lines else "Nothing new. Every season is up to date.")

        self.run_bg(work, done, "Checking for new seasons...")


if __name__ == "__main__":
    App().mainloop()