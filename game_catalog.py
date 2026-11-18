"""Mega Drive game catalog, built with Tkinter and SQLite."""

from __future__ import annotations

import sqlite3
import re
import csv
import json
from decimal import Decimal
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = ImageTk = None


DB_PATH = Path(__file__).with_name("games.db")
CSV_FIELDS = (
    ("title", "タイトル"),
    ("title_en", "英語タイトル"),
    ("publisher", "発売元"),
    ("release_year", "発売年"),
    ("region", "地域・型番"),
    ("genre", "ジャンル"),
    ("reader_race_rank", "読者レース順位"),
    ("reader_race_score", "読者レース全投票平均スコア"),
    ("image_path", "タイトル画像パス"),
    ("notes", "メモ"),
)
GENRES = (
    "A・ACT", "A・RPG", "ACT", "ADV", "ETC", "PIN", "PUZ", "QIZ", "RAC",
    "RPG", "SHT", "SHT/SLG", "SLG", "SPT", "TAB", "VCS", "VIC",
)


class CatalogDB:
    def __init__(self, path: Path = DB_PATH):
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                title_en TEXT DEFAULT '',
                publisher TEXT DEFAULT '',
                release_year TEXT DEFAULT '',
                region TEXT DEFAULT '',
                genre TEXT DEFAULT '',
                reader_race_rank TEXT DEFAULT '',
                reader_race_score TEXT DEFAULT '',
                image_path TEXT DEFAULT '',
                notes TEXT DEFAULT ''
            )"""
        )
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        # Add the field to catalogs created by earlier versions of the app.
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(games)")}
        if "reader_race_score" not in columns:
            self.connection.execute("ALTER TABLE games ADD COLUMN reader_race_score TEXT DEFAULT ''")
        if "reader_race_rank" not in columns:
            self.connection.execute("ALTER TABLE games ADD COLUMN reader_race_rank TEXT DEFAULT ''")
        if "image_path" not in columns:
            self.connection.execute("ALTER TABLE games ADD COLUMN image_path TEXT DEFAULT ''")
        self.connection.commit()

    def list_games(self, query: str = "", genre: str = "", year: str = "") -> list[sqlite3.Row]:
        pattern = f"%{query}%"
        return self.connection.execute(
            """SELECT * FROM games
               WHERE (title LIKE ? OR title_en LIKE ? OR publisher LIKE ?
                     OR release_year LIKE ? OR region LIKE ? OR genre LIKE ?
                     OR reader_race_rank LIKE ? OR reader_race_score LIKE ? OR notes LIKE ?)
                 AND (? = '' OR genre = ?)
                 AND (? = '' OR release_year = ?)
               ORDER BY title COLLATE NOCASE, id""",
            (pattern, pattern, pattern, pattern, pattern, pattern, pattern, pattern, pattern,
             genre, genre, year, year),
        ).fetchall()

    def save(self, values: dict[str, str], game_id: int | None = None) -> None:
        fields = ("title", "title_en", "publisher", "release_year", "region", "genre", "reader_race_rank", "reader_race_score", "image_path", "notes")
        if game_id is None:
            self.connection.execute(
                f"INSERT INTO games ({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)})",
                tuple(values[f] for f in fields),
            )
        else:
            self.connection.execute(
                f"UPDATE games SET {', '.join(f'{f} = ?' for f in fields)} WHERE id = ?",
                (*[values[f] for f in fields], game_id),
            )
        self.connection.commit()

    def insert_many(self, games: list[dict[str, str]]) -> None:
        fields = tuple(key for key, _label in CSV_FIELDS)
        with self.connection:
            self.connection.executemany(
                f"INSERT INTO games ({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)})",
                [tuple(game[field] for field in fields) for game in games],
            )

    def delete(self, game_id: int) -> None:
        self.connection.execute("DELETE FROM games WHERE id = ?", (game_id,))
        self.connection.commit()

    def get_setting(self, key: str) -> str | None:
        row = self.connection.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_setting(self, key: str, value: str) -> None:
        self.connection.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.connection.commit()


class GameDialog(tk.Toplevel):
    FIELDS = [
        ("title", "タイトル *"),
        ("title_en", "英語タイトル"),
        ("publisher", "発売元"),
        ("release_year", "発売年"),
        ("region", "地域 / 型番"),
        ("genre", "ジャンル"),
        ("reader_race_rank", "読者レース 順位"),
        ("reader_race_score", "読者レース 全投票平均スコア"),
        ("image_path", "タイトル画像"),
    ]

    def __init__(self, parent: tk.Misc, initial: sqlite3.Row | None = None):
        super().__init__(parent)
        self.title("ゲームを編集" if initial else "ゲームを追加")
        self.transient(parent)
        self.grab_set()
        self.result: dict[str, str] | None = None
        self.entries: dict[str, tk.Entry] = {}
        frame = ttk.Frame(self, padding=16)
        frame.grid(sticky="nsew")
        frame.columnconfigure(1, weight=1)
        for row, (key, label) in enumerate(self.FIELDS):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
            if key == "image_path":
                image_frame = ttk.Frame(frame)
                image_frame.grid(row=row, column=1, sticky="ew", pady=5)
                image_frame.columnconfigure(0, weight=1)
                entry = ttk.Entry(image_frame, width=30)
                entry.grid(row=0, column=0, sticky="ew")
                ttk.Button(image_frame, text="参照...", command=lambda e=entry: self._browse_image(e)).grid(row=0, column=1, padx=(6, 0))
                ttk.Button(image_frame, text="解除", command=lambda e=entry: (e.delete(0, "end"))).grid(row=0, column=2, padx=(4, 0))
            elif key == "genre":
                entry = ttk.Combobox(frame, width=35, values=GENRES, state="readonly")
                entry.grid(row=row, column=1, sticky="ew", pady=5)
            else:
                entry = ttk.Entry(frame, width=38)
                entry.grid(row=row, column=1, sticky="ew", pady=5)
            if initial:
                if key == "genre":
                    entry.set(initial[key] or "")
                else:
                    entry.insert(0, initial[key] or "")
            self.entries[key] = entry
        notes_row = len(self.FIELDS)
        ttk.Label(frame, text="メモ").grid(row=notes_row, column=0, sticky="nw", padx=(0, 12), pady=5)
        self.notes = tk.Text(frame, width=38, height=5, wrap="word")
        self.notes.grid(row=notes_row, column=1, sticky="ew", pady=5)
        if initial:
            self.notes.insert("1.0", initial["notes"] or "")
        buttons = ttk.Frame(frame)
        buttons.grid(row=notes_row + 1, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="キャンセル", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="保存", command=self._save).pack(side="right")
        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Return>", lambda _event: self._save())
        self.entries["title"].focus_set()
        self.wait_visibility()
        self.geometry(f"+{parent.winfo_rootx() + 120}+{parent.winfo_rooty() + 80}")

    def _browse_image(self, entry: tk.Entry) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="タイトル画像を選択",
            filetypes=[("画像ファイル", "*.png *.jpg *.jpeg *.gif *.bmp"), ("すべてのファイル", "*.*")],
        )
        if path:
            entry.delete(0, "end")
            entry.insert(0, path)

    def _save(self) -> None:
        title = self.entries["title"].get().strip()
        if not title:
            messagebox.showwarning("入力を確認", "タイトルを入力してください。", parent=self)
            self.entries["title"].focus_set()
            return
        score = self.entries["reader_race_score"].get().strip()
        if score and not re.fullmatch(r"[0-9](?:\.[0-9]{1,4})?", score):
            messagebox.showwarning(
                "入力を確認",
                "全投票平均スコアは 9、9.42、6.2934 の形式で入力してください（小数点以下0〜4桁、最大9.9999）。",
                parent=self,
            )
            self.entries["reader_race_score"].focus_set()
            return
        rank = self.entries["reader_race_rank"].get().strip()
        if rank and (not rank.isdecimal() or int(rank) < 1):
            messagebox.showwarning("入力を確認", "順位は1以上の整数で入力してください。", parent=self)
            self.entries["reader_race_rank"].focus_set()
            return
        self.result = {key: entry.get().strip() for key, entry in self.entries.items()}
        self.result["notes"] = self.notes.get("1.0", "end-1c").strip()
        self.destroy()


class GameCatalogApp(tk.Tk):
    COLUMNS = (
        ("title", "タイトル", 240),
        ("title_en", "英語タイトル", 210),
        ("publisher", "発売元", 140),
        ("release_year", "年", 65),
        ("region", "地域 / 型番", 130),
        ("genre", "ジャンル", 110),
        ("reader_race_rank", "読者レース順位", 110),
        ("reader_race_score", "読者レース平均", 125),
        ("image_path", "タイトル画像", 0),
    )

    def __init__(self):
        super().__init__()
        self.db = CatalogDB()
        self.title("メガドライブ ゲームカタログ")
        self.geometry("1050x650")
        self.minsize(760, 450)
        self.sort_key = "title"
        self.sort_reverse = False
        self.search_committed = ""
        self.available_columns = tuple(key for key, _label, _width in self.COLUMNS if key != "image_path")
        try:
            saved_columns = json.loads(self.db.get_setting("visible_columns") or "null")
        except (json.JSONDecodeError, TypeError):
            saved_columns = None
        if isinstance(saved_columns, list):
            self.visible_columns = tuple(key for key in self.available_columns if key in saved_columns)
        else:
            self.visible_columns = self.available_columns
        if not self.visible_columns:
            self.visible_columns = self.available_columns
        self._build_ui()
        self.image_refs: list[tk.PhotoImage] = []
        self.refresh()
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        header = ttk.Frame(self, padding=(16, 14, 16, 8))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="メガドライブ ゲームカタログ", font=("Yu Gothic UI", 17, "bold")).grid(
            row=0, column=0, sticky="w", padx=(0, 20)
        )
        ttk.Label(header, text="検索").grid(row=0, column=1, sticky="w")
        self.search_var = tk.StringVar()
        search = ttk.Entry(header, textvariable=self.search_var, width=32)
        search.grid(row=0, column=2, sticky="ew", padx=(8, 0))
        search.bind("<Return>", lambda _event: self.run_search())
        header.columnconfigure(2, weight=1)
        ttk.Button(header, text="検索", command=self.run_search).grid(row=0, column=3, padx=(8, 0))
        self.view_var = tk.StringVar(value="list")
        ttk.Radiobutton(header, text="リスト", variable=self.view_var, value="list", command=self._switch_view).grid(row=0, column=4, padx=(12, 2))
        ttk.Radiobutton(header, text="画像", variable=self.view_var, value="cards", command=self._switch_view).grid(row=0, column=5, padx=(2, 0))

        filters = ttk.Frame(self, padding=(16, 0, 16, 8))
        filters.grid(row=1, column=0, sticky="ew")
        ttk.Label(filters, text="ジャンル").pack(side="left")
        self.genre_filter = tk.StringVar(value="すべて")
        self.genre_combo = ttk.Combobox(filters, textvariable=self.genre_filter, values=("すべて", *GENRES), state="readonly", width=12)
        self.genre_combo.pack(side="left", padx=(6, 16))
        self.genre_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh())
        ttk.Label(filters, text="発売年").pack(side="left")
        self.year_filter = tk.StringVar(value="すべて")
        self.year_combo = ttk.Combobox(filters, textvariable=self.year_filter, values=("すべて",), state="readonly", width=12)
        self.year_combo.pack(side="left", padx=(6, 0))
        self.year_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh())
        ttk.Button(filters, text="表示列...", command=self.choose_columns).pack(side="right")

        body = ttk.Frame(self, padding=(16, 0, 16, 12))
        body.grid(row=2, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self.results = ttk.Frame(body)
        self.results.grid(row=0, column=0, sticky="nsew")
        self.results.columnconfigure(0, weight=1)
        self.results.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(self.results, columns=[c[0] for c in self.COLUMNS], show="headings", selectmode="browse")
        self.tree.configure(displaycolumns=self.visible_columns)
        for key, label, width in self.COLUMNS:
            heading = f"{label} ▲" if key == self.sort_key else label
            self.tree.heading(key, text=heading, command=lambda k=key: self.sort_by(k))
            self.tree.column(key, width=width, minwidth=55, anchor="w")
        self.tree.column("image_path", width=0, stretch=False)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree_scroll = ttk.Scrollbar(self.results, orient="vertical", command=self.tree.yview)
        self.tree_scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=self.tree_scroll.set)
        self.tree.bind("<Double-1>", lambda _event: self.edit_game())
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self.show_details())
        self.tree.bind("<Delete>", lambda _event: self.delete_game())
        self.card_canvas = tk.Canvas(self.results, highlightthickness=0)
        self.card_scroll = ttk.Scrollbar(self.results, orient="vertical", command=self.card_canvas.yview)
        self.card_canvas.configure(yscrollcommand=self.card_scroll.set)
        self.card_inner = ttk.Frame(self.card_canvas, padding=8)
        self.card_window = self.card_canvas.create_window((0, 0), window=self.card_inner, anchor="nw")
        self.card_inner.bind("<Configure>", lambda _event: self.card_canvas.configure(scrollregion=self.card_canvas.bbox("all")))
        self.card_canvas.bind("<Configure>", lambda event: self.card_canvas.itemconfigure(self.card_window, width=event.width))

        details = ttk.LabelFrame(body, text="作品メモ", padding=10)
        details.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        details.columnconfigure(0, weight=1)
        self.detail_text = tk.Text(details, height=3, wrap="word", state="disabled", relief="flat", background=self.cget("background"))
        self.detail_text.grid(row=0, column=0, sticky="ew")

        footer = ttk.Frame(self, padding=(16, 0, 16, 14))
        footer.grid(row=3, column=0, sticky="ew")
        self.count_label = ttk.Label(footer, text="0 件")
        self.count_label.pack(side="left")
        ttk.Button(footer, text="削除", command=self.delete_game).pack(side="right", padx=(8, 0))
        ttk.Button(footer, text="編集", command=self.edit_game).pack(side="right", padx=(8, 0))
        ttk.Button(footer, text="CSV一括登録", command=self.import_csv).pack(side="right", padx=(8, 0))
        ttk.Button(footer, text="CSVテンプレート", command=self.export_csv_template).pack(side="right", padx=(8, 0))
        ttk.Button(footer, text="ゲームを追加", command=self.add_game).pack(side="right")
        self.bind("<Control-n>", lambda _event: self.add_game())
        self.bind("<Control-f>", lambda _event: search.focus_set())

    def refresh(self) -> None:
        selected = self.tree.selection()[0] if self.tree.selection() else None
        self.tree.delete(*self.tree.get_children())
        rows = self.db.list_games(
            self.search_committed,
            "" if self.genre_filter.get() == "すべて" else self.genre_filter.get(),
            "" if self.year_filter.get() == "すべて" else self.year_filter.get(),
        )
        self._update_year_filter()
        populated = [game for game in rows if (game[self.sort_key] or "").strip()]
        empty = [game for game in rows if not (game[self.sort_key] or "").strip()]
        populated.sort(key=lambda game: self._sort_value(self.sort_key, game[self.sort_key]), reverse=self.sort_reverse)
        rows = populated + empty
        for game in rows:
            self.tree.insert("", "end", iid=str(game["id"]), values=tuple(game[c[0]] or "" for c in self.COLUMNS))
        self._render_cards(rows)
        self.count_label.configure(text=f"{len(rows)} 件")
        if selected and self.tree.exists(selected):
            self.tree.selection_set(selected)
        else:
            self._set_detail("")

    def run_search(self) -> None:
        self.search_committed = self.search_var.get().strip()
        self.refresh()

    @staticmethod
    def _sort_value(key: str, value: str):
        value = (value or "").strip()
        if key in ("release_year", "reader_race_rank") and value.isdecimal():
            return (0, int(value))
        if key == "reader_race_score":
            try:
                return (0, Decimal(value))
            except Exception:
                pass
        return (1, value.casefold())

    def sort_by(self, key: str) -> None:
        if key == "image_path":
            return
        if self.sort_key == key:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_key = key
            self.sort_reverse = False
        for column, label, _width in self.COLUMNS:
            heading = label
            if column == self.sort_key:
                heading += " ▼" if self.sort_reverse else " ▲"
            self.tree.heading(column, text=heading)
        self.refresh()

    def choose_columns(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("表示する列")
        dialog.transient(self)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=16)
        frame.grid(sticky="nsew")
        ttk.Label(frame, text="一覧に表示する項目を選択してください").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        variables: dict[str, tk.BooleanVar] = {}
        labels = {key: label for key, label, _width in self.COLUMNS}
        for index, key in enumerate(self.available_columns):
            variable = tk.BooleanVar(value=key in self.visible_columns)
            variables[key] = variable
            ttk.Checkbutton(frame, text=labels[key], variable=variable).grid(
                row=1 + index // 2, column=index % 2, sticky="w", padx=(0, 18), pady=3
            )

        def apply() -> None:
            selected = tuple(key for key in self.available_columns if variables[key].get())
            if not selected:
                messagebox.showwarning("列を選択", "少なくとも1つの列を選択してください。", parent=dialog)
                return
            self.visible_columns = selected
            self.tree.configure(displaycolumns=selected)
            self.db.set_setting("visible_columns", json.dumps(selected, ensure_ascii=False))
            dialog.destroy()

        buttons = ttk.Frame(frame)
        buttons.grid(row=1 + (len(self.available_columns) + 1) // 2, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="キャンセル", command=dialog.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="適用", command=apply).pack(side="right")
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.wait_visibility()
        dialog.geometry(f"+{self.winfo_rootx() + 150}+{self.winfo_rooty() + 100}")

    def _update_year_filter(self) -> None:
        current = self.year_filter.get()
        years = [row[0] for row in self.db.connection.execute(
            "SELECT DISTINCT release_year FROM games WHERE release_year <> ''"
        )]
        years.sort(key=lambda year: (0, int(year)) if year.isdecimal() else (1, year.casefold()))
        choices = ("すべて", *years)
        self.year_combo.configure(values=choices)
        if current not in choices:
            self.year_filter.set("すべて")

    def _switch_view(self) -> None:
        if self.view_var.get() == "cards":
            self.tree.grid_remove()
            self.tree_scroll.grid_remove()
            self.results.rowconfigure(0, weight=1)
            self.card_canvas.grid(row=0, column=0, sticky="nsew")
            self.card_scroll.grid(row=0, column=1, sticky="ns")
        else:
            self.card_canvas.grid_remove()
            self.card_scroll.grid_remove()
            self.tree.grid()
            self.tree_scroll.grid()

    def _render_cards(self, games: list[sqlite3.Row]) -> None:
        for child in self.card_inner.winfo_children():
            child.destroy()
        self.image_refs.clear()
        columns = max(1, min(4, self.card_canvas.winfo_width() // 210))
        for index, game in enumerate(games):
            card = ttk.Frame(self.card_inner, relief="ridge", padding=8)
            card.grid(row=index // columns, column=index % columns, sticky="nsew", padx=6, pady=6)
            self.card_inner.columnconfigure(index % columns, weight=1)
            image = self._load_thumbnail(game["image_path"] or "")
            if image:
                image_label = ttk.Label(card, image=image)
                image_label.image = image
                self.image_refs.append(image)
            else:
                image_label = ttk.Label(card, text="画像なし", anchor="center", width=24, padding=18)
            image_label.pack(fill="x", pady=(0, 6))
            title_label = ttk.Label(card, text=game["title"], font=("Yu Gothic UI", 10, "bold"), wraplength=185, justify="center")
            title_label.pack(fill="x")
            subtitle = " / ".join(x for x in (game["title_en"], game["release_year"]) if x)
            if subtitle:
                ttk.Label(card, text=subtitle, wraplength=185, justify="center").pack(fill="x", pady=(2, 0))
            race = "  ".join(x for x in (
                f"順位 {game['reader_race_rank']}位" if game["reader_race_rank"] else "",
                f"平均 {game['reader_race_score']}" if game["reader_race_score"] else "",
            ) if x)
            if race:
                ttk.Label(card, text=race, justify="center").pack(fill="x", pady=(4, 0))
            for widget in (card, image_label, title_label):
                widget.bind("<Button-1>", lambda _event, gid=str(game["id"]): self._select_game(gid))

    @staticmethod
    def _load_thumbnail(path: str) -> tk.PhotoImage | None:
        if not path or not Path(path).is_file():
            return None
        try:
            if Image is not None:
                with Image.open(path) as source:
                    source.thumbnail((180, 180))
                    return ImageTk.PhotoImage(source.copy())
            image = tk.PhotoImage(file=path)
            factor = max(1, (max(image.width(), image.height()) + 179) // 180)
            return image.subsample(factor, factor)
        except Exception:
            return None

    def _select_game(self, game_id: str) -> None:
        if self.tree.exists(game_id):
            self.tree.selection_set(game_id)
            self.tree.focus(game_id)
            self.show_details()

    def _selected_game(self) -> sqlite3.Row | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return self.db.connection.execute("SELECT * FROM games WHERE id = ?", (int(selection[0]),)).fetchone()

    def _set_detail(self, text: str) -> None:
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", text)
        self.detail_text.configure(state="disabled")

    def show_details(self) -> None:
        game = self._selected_game()
        if game:
            self._set_detail(game["notes"] or "メモはありません。")

    def add_game(self) -> None:
        dialog = GameDialog(self)
        if dialog.result:
            self.db.save(dialog.result)
            self.refresh()

    def export_csv_template(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self,
            title="CSVテンプレートを保存",
            defaultextension=".csv",
            initialfile="game_catalog_template.csv",
            filetypes=[("CSVファイル", "*.csv")],
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as file:
                writer = csv.writer(file)
                writer.writerow([label for _key, label in CSV_FIELDS])
                writer.writerow(["サンプルタイトル", "Sample Game", "セガ", "1990", "日本", "ACT", "1", "6.2934", "", "サンプル行。登録前に削除してください"])
            messagebox.showinfo("保存しました", "CSVテンプレートを保存しました。サンプル行を置き換えてご利用ください。", parent=self)
        except OSError as error:
            messagebox.showerror("保存できません", str(error), parent=self)

    def import_csv(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="登録するCSVを選択",
            filetypes=[("CSVファイル", "*.csv"), ("すべてのファイル", "*.*")],
        )
        if not path:
            return
        try:
            try:
                with open(path, "r", newline="", encoding="utf-8-sig") as file:
                    reader = csv.DictReader(file)
                    rows = list(reader)
                    headers = reader.fieldnames or []
            except UnicodeDecodeError:
                with open(path, "r", newline="", encoding="cp932") as file:
                    reader = csv.DictReader(file)
                    rows = list(reader)
                    headers = reader.fieldnames or []
        except (OSError, csv.Error) as error:
            messagebox.showerror("読み込みエラー", f"CSVを読み込めませんでした。\n{error}", parent=self)
            return

        key_by_header = {key: key for key, _label in CSV_FIELDS}
        key_by_header.update({label: key for key, label in CSV_FIELDS})
        header_map = {key_by_header.get((header or "").strip()): header for header in headers}
        if "title" not in header_map:
            messagebox.showerror("CSV形式を確認", "CSVに「タイトル」または title 列が必要です。テンプレートを使ってください。", parent=self)
            return

        games: list[dict[str, str]] = []
        errors: list[str] = []
        for line, row in enumerate(rows, start=2):
            if not any(isinstance(value, str) and value.strip() for value in row.values()):
                continue
            game = {
                key: (row.get(header).strip() if isinstance(row.get(header), str) else "")
                for key, header in header_map.items()
                if key
            }
            for key, _label in CSV_FIELDS:
                game.setdefault(key, "")
            if not game["title"]:
                errors.append(f"{line}行目: タイトルが空です")
                continue
            score = game["reader_race_score"]
            if score and not re.fullmatch(r"[0-9](?:\.[0-9]{1,4})?", score):
                errors.append(f"{line}行目: スコアは整数または小数点以下1〜4桁、最大9.9999で入力してください")
                continue
            rank = game["reader_race_rank"]
            if rank and (not rank.isdecimal() or int(rank) < 1):
                errors.append(f"{line}行目: 順位は1以上の整数で入力してください")
                continue
            if game["genre"] and game["genre"] not in GENRES:
                errors.append(f"{line}行目: ジャンル「{game['genre']}」は選択肢にありません")
                continue
            image_path = game["image_path"]
            if image_path and not Path(image_path).is_absolute():
                game["image_path"] = str((Path(path).resolve().parent / image_path).resolve())
            games.append(game)

        if errors:
            preview = "\n".join(errors[:10])
            suffix = f"\nほか{len(errors) - 10}件" if len(errors) > 10 else ""
            messagebox.showerror(
                "CSVの内容を確認",
                f"入力エラーが{len(errors)}件あります。1件も登録していません。\n\n{preview}{suffix}",
                parent=self,
            )
            return
        if not games:
            messagebox.showinfo("登録対象なし", "CSVに登録できるデータ行がありません。", parent=self)
            return
        if not messagebox.askyesno("一括登録の確認", f"{len(games)}件をカタログに追加しますか？", parent=self):
            return
        try:
            self.db.insert_many(games)
        except sqlite3.Error as error:
            messagebox.showerror("登録エラー", f"CSVを登録できませんでした。\n{error}", parent=self)
            return
        self.refresh()
        messagebox.showinfo("登録しました", f"{len(games)}件を登録しました。", parent=self)

    def edit_game(self) -> None:
        game = self._selected_game()
        if not game:
            return
        dialog = GameDialog(self, game)
        if dialog.result:
            self.db.save(dialog.result, game["id"])
            self.refresh()

    def delete_game(self) -> None:
        game = self._selected_game()
        if game and messagebox.askyesno("削除の確認", f"「{game['title']}」を削除しますか？", parent=self):
            self.db.delete(game["id"])
            self.refresh()

    def _close(self) -> None:
        self.db.connection.close()
        self.destroy()


if __name__ == "__main__":
    GameCatalogApp().mainloop()
