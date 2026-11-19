"""Слой работы с базой данных (SQLite).

Файлы на диске НЕ трогаются: мы храним только информацию о них.

Сущности (как в Steam):
  * теги        - цветные плашки-описания файла (Картинки, Школа, 2026).
                  У тега может быть ГРУППА (как "Жанр" / "Тематика" в Steam).
  * коллекции   - "полки" в боковой панели:
        - обычные      : ты сам кладёшь в них файлы
        - динамические : наполняются сами по правилам (теги, расширения, размер, дата)
  * избранное   - звёздочка у файла
  * папки библиотеки - папки, за которыми следим (как "папки библиотеки" в Steam).
    Если файл пропал с диска, запись НЕ удаляется: у неё ставится missing_since.
    Нашёлся (вернули флешку, нашли перемещённый) - отметка снимается, теги на месте.

Фильтр по тегам (как в магазине Steam):
  * include - нужные теги, exclude - исключённые теги
  * mode = "all" - у файла должны быть ВСЕ нужные теги (И)
    mode = "any" - хотя бы ОДИН из нужных (ИЛИ)
"""
import fnmatch
import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app import query
from app.paths import DB_NAME, db_path

# Цвета для новых тегов (выдаются по кругу)
PALETTE = [
    "#e8590c", "#f08c00", "#74b816", "#12b886", "#15aabf",
    "#4c6ef5", "#7950f2", "#d6336c", "#e03131", "#868e96",
]

AUTO_GROUP = "Тип файла"

# значки авто-тегов по умолчанию (можно поменять в «Значок тега…»)
AUTO_ICONS = {
    "Картинки": "🖼", "Документы": "📄", "Таблицы": "📊", "Презентации": "📽",
    "Видео": "🎬", "Музыка": "🎵", "Архивы": "🗜", "Код": "💻",
}

# Авто-теги по расширению файла: название -> (цвет, расширения)
AUTO_TAGS = {
    "Картинки":    ("#e8590c", (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg")),
    "Документы":   ("#4c6ef5", (".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".md")),
    "Таблицы":     ("#12b886", (".xls", ".xlsx", ".csv")),
    "Презентации": ("#f08c00", (".ppt", ".pptx")),
    "Видео":       ("#d6336c", (".mp4", ".mkv", ".avi", ".mov", ".webm")),
    "Музыка":      ("#7950f2", (".mp3", ".wav", ".flac", ".ogg", ".m4a")),
    "Архивы":      ("#868e96", (".zip", ".rar", ".7z", ".tar", ".gz")),
    "Код":         ("#15aabf", (".py", ".js", ".ts", ".html", ".css", ".cpp", ".c", ".java", ".cs")),
}
EXT_TO_AUTO = {ext: name for name, (_c, exts) in AUTO_TAGS.items() for ext in exts}

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    path      TEXT NOT NULL UNIQUE,
    name      TEXT NOT NULL,
    ext       TEXT DEFAULT '',
    size      INTEGER DEFAULT 0,
    favorite  INTEGER DEFAULT 0,
    added_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    mtime     REAL DEFAULT 0,       -- время изменения файла на диске
    dev       TEXT DEFAULT '',      -- том диска  } вместе - "номер" файла в системе:
    inode     TEXT DEFAULT '',      -- id файла   } при перемещении по диску не меняется
    missing_since TEXT,             -- NULL = файл на месте, иначе когда пропал
    qhash     TEXT,                 -- быстрый отпечаток (начало+конец файла) - для дубликатов
    fhash     TEXT,                 -- полный отпечаток содержимого (BLAKE2b)
    rating    INTEGER DEFAULT 0,    -- оценка 0..5
    note      TEXT DEFAULT '',      -- заметка к файлу
    last_opened TEXT,               -- когда открывали из программы (для «Недавних»)
    colors    TEXT                  -- главные цвета картинки: "красный,синий" (NULL - ещё не считали)
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- файлы, которые пользователь убрал из библиотеки: слежение не добавит их снова
CREATE TABLE IF NOT EXISTS hidden_paths (
    path TEXT PRIMARY KEY
);

-- папки, за которыми следим: новые файлы в них добавляются сами,
-- а перемещённые внутри них - находятся
CREATE TABLE IF NOT EXISTS folders (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    path      TEXT NOT NULL UNIQUE,
    added_at  TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tags (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT NOT NULL UNIQUE COLLATE NOCASE,
    color    TEXT DEFAULT '#4c6ef5',
    is_auto  INTEGER DEFAULT 0,
    grp      TEXT DEFAULT '',
    parent_id INTEGER REFERENCES tags(id) ON DELETE SET NULL, -- вложенный тег: Кошки -> Животные
    icon     TEXT DEFAULT '',       -- символ значка (эмодзи/буква); пусто - первая буква тега
    icon_image TEXT DEFAULT ''      -- своя картинка значка (файл в папке программы)
);

-- "Многие ко многим": у файла много тегов, у тега много файлов.
CREATE TABLE IF NOT EXISTS file_tags (
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tags(id)  ON DELETE CASCADE,
    PRIMARY KEY (file_id, tag_id)
);
CREATE INDEX IF NOT EXISTS idx_file_tags_tag ON file_tags(tag_id);

-- rules = NULL        -> обычная коллекция
-- rules = JSON-строка -> динамическая, например
--   {"tags":[1,2],"exclude_tags":[5],"tag_mode":"any","exts":[".pdf"],"min_kb":500,"days":30,
--    "query":"#Школа размер>1мб"}
CREATE TABLE IF NOT EXISTS collections (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT NOT NULL UNIQUE COLLATE NOCASE,
    rules TEXT
);

-- правила авто-тегов: "если файл лежит в папке Школа - поставить тег Школа"
-- kind: folder (имя папки в пути), name (имя файла, можно *), ext (расширения), path (часть пути)
CREATE TABLE IF NOT EXISTS auto_rules (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    tag_id  INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    kind    TEXT NOT NULL,
    value   TEXT NOT NULL,
    enabled INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS file_collections (
    file_id       INTEGER NOT NULL REFERENCES files(id)       ON DELETE CASCADE,
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    PRIMARY KEY (file_id, collection_id)
);
"""


# Что не добавляем в библиотеку: служебные файлы Windows/Office, недокачанные файлы,
# а также собственные файлы программы (база и кэш обложек).
IGNORED_NAMES = {"desktop.ini", "thumbs.db", ".ds_store"}
IGNORED_SUFFIXES = (".tmp", ".crdownload", ".part", ".partial", ".download")
IGNORED_DIRS = {"thumbs_cache", "$recycle.bin", "system volume information", "__pycache__"}


def is_ignored(path):
    name = os.path.basename(path).lower()
    if name in IGNORED_NAMES or name.startswith("~$") or name.endswith(IGNORED_SUFFIXES):
        return True
    if name.startswith(DB_NAME):  # virtual_explorer.db и его -journal
        return True
    parts = {p.lower() for p in Path(path).parts[:-1]}
    return bool(parts & IGNORED_DIRS)


def stat_info(path):
    """(размер, время изменения, том, номер файла) или None, если файла нет.

    На Windows (NTFS) st_dev + st_ino - уникальный номер файла, который не меняется
    при перемещении/переименовании в пределах диска. По нему и находим переехавшие файлы.
    """
    try:
        st = os.stat(path)
    except (OSError, ValueError):
        return None
    if not os.path.isfile(path):
        return None
    ino = str(st.st_ino) if st.st_ino else ""
    return (st.st_size, st.st_mtime, str(st.st_dev), ino)


def is_inside(path, folder):
    """Лежит ли path внутри folder (или совпадает с ней). Без учёта регистра на Windows."""
    p = os.path.normcase(os.path.normpath(path))
    f = os.path.normcase(os.path.normpath(folder))
    return p == f or p.startswith(f.rstrip("\\/") + os.sep)


def topmost_dirs(dirs):
    result = []
    for d in sorted({os.path.normpath(d) for d in dirs if d}, key=len):
        if not any(is_inside(d, r) for r in result):
            result.append(d)
    return result


def _py_normcase(value):
    return os.path.normcase(value) if isinstance(value, str) else value


def _py_lower(value):
    """lower() для SQLite: встроенный LIKE не понимает регистр у кириллицы."""
    return value.lower() if isinstance(value, str) else value


# файл, у которого в библиотеке есть другой файл с тем же содержимым
DUP_SQL = ("(f.fhash IS NOT NULL AND f.missing_since IS NULL AND EXISTS (SELECT 1 FROM files g "
           "WHERE g.fhash = f.fhash AND g.id <> f.id AND g.missing_since IS NULL))")


class Facet(dict):
    """Строка тега + cnt; читается как sqlite3.Row: facet["name"], facet["cnt"]."""

    def __init__(self, row, cnt):
        super().__init__(row)
        self["cnt"] = cnt


@dataclass
class FileFilter:
    """Всё, что сейчас выбрано в интерфейсе, одним объектом."""
    include: tuple = ()        # нужные теги
    exclude: tuple = ()        # исключённые теги
    mode: str = "all"          # "all" (И) или "any" (ИЛИ)
    search: str = ""
    favorites: bool = False
    no_user_tags: bool = False # без персонализированных тегов (авто-теги не считаются)
    no_tags: bool = False      # совсем без тегов: даже авто-тег не подобрался (неизвестный тип)
    no_auto_tags: bool = False # без авто-тегов (свои теги могут быть)
    missing: bool = False      # только потерянные (нет на диске)
    duplicates: bool = False   # только файлы, у которых есть копии с тем же содержимым
    recent: bool = False       # только открывавшиеся из программы («Недавние»)
    folder: str = ""           # только файлы внутри этой папки (папки в сайдбаре)
    collection: dict = None    # коллекция из get_collections()


class Database:
    def __init__(self, path=None):
        self.path = str(path or db_path())
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.create_function("py_lower", 1, _py_lower, deterministic=True)
        self.conn.create_function("py_normcase", 1, _py_normcase, deterministic=True)
        self.conn.execute("PRAGMA foreign_keys = ON")
        # быстрее и надёжнее при частой записи: журнал WAL, меньше ожиданий диска, кэш в памяти
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self.conn.execute("PRAGMA temp_store = MEMORY")
        self.conn.execute("PRAGMA cache_size = -32000")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _columns(self, table):
        return {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}

    def _migrate(self):
        """Дополняет базу от прошлых версий новыми колонками."""
        files_cols = self._columns("files")
        if "ext" not in files_cols:
            self.conn.execute("ALTER TABLE files ADD COLUMN ext TEXT DEFAULT ''")
        if "favorite" not in files_cols:
            self.conn.execute("ALTER TABLE files ADD COLUMN favorite INTEGER DEFAULT 0")
        if "added_at" not in files_cols:
            self.conn.execute("ALTER TABLE files ADD COLUMN added_at TEXT")
        for col, decl in [("mtime", "REAL DEFAULT 0"), ("dev", "TEXT DEFAULT ''"),
                          ("inode", "TEXT DEFAULT ''"), ("missing_since", "TEXT"),
                          ("qhash", "TEXT"), ("fhash", "TEXT"), ("rating", "INTEGER DEFAULT 0"),
                          ("note", "TEXT DEFAULT ''"), ("last_opened", "TEXT"), ("colors", "TEXT")]:
            if col not in files_cols:
                self.conn.execute(f"ALTER TABLE files ADD COLUMN {col} {decl}")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_files_inode ON files(inode)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_files_size ON files(size)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_files_name ON files(name)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_files_fhash ON files(fhash)")
        tag_cols = self._columns("tags")
        if "is_auto" not in tag_cols:
            self.conn.execute("ALTER TABLE tags ADD COLUMN is_auto INTEGER DEFAULT 0")
        if "grp" not in tag_cols:
            self.conn.execute("ALTER TABLE tags ADD COLUMN grp TEXT DEFAULT ''")
        for col in ("icon", "icon_image"):
            if col not in tag_cols:
                self.conn.execute(f"ALTER TABLE tags ADD COLUMN {col} TEXT DEFAULT ''")
        for name, icon in AUTO_ICONS.items():  # значки авто-тегов по умолчанию
            self.conn.execute("UPDATE tags SET icon = ? WHERE is_auto = 1 AND name = ? "
                              "AND (icon IS NULL OR icon = '')", (icon, name))
        if "parent_id" not in tag_cols:
            self.conn.execute("ALTER TABLE tags ADD COLUMN parent_id INTEGER "
                              "REFERENCES tags(id) ON DELETE SET NULL")

        self.conn.execute(
            "UPDATE files SET added_at = datetime('now') WHERE added_at IS NULL"
        )
        self._guess_folders_from_v05()
        self.conn.execute("UPDATE tags SET grp = '' WHERE grp IS NULL")
        # авто-теги из v0.3 кладём в группу "Тип файла"
        self.conn.execute(
            "UPDATE tags SET grp = ? WHERE is_auto = 1 AND grp = ''", (AUTO_GROUP,)
        )
        for row in self.conn.execute(
            "SELECT id, name FROM files WHERE ext IS NULL OR ext = ''"
        ).fetchall():
            self.conn.execute(
                "UPDATE files SET ext = ? WHERE id = ?",
                (Path(row["name"]).suffix.lower(), row["id"]),
            )

    def _guess_folders_from_v05(self):
        """До v0.6 папки не запоминались. Восстанавливаем их по путям файлов:
        берём папки файлов и оставляем только самые верхние."""
        if self.conn.execute("SELECT 1 FROM folders LIMIT 1").fetchone():
            return
        dirs = {os.path.dirname(r["path"]) for r in self.conn.execute("SELECT path FROM files")}
        for d in topmost_dirs(dirs):
            self.conn.execute("INSERT OR IGNORE INTO folders (path) VALUES (?)", (d,))

    # ================= папки библиотеки =================
    def get_folder_rows(self):
        return self.conn.execute("SELECT id, path FROM folders ORDER BY path").fetchall()

    def get_folder_path(self, folder_id):
        row = self.conn.execute("SELECT path FROM folders WHERE id = ?", (folder_id,)).fetchone()
        return row["path"] if row else None

    def get_folders(self):
        return [r["path"] for r in self.conn.execute("SELECT path FROM folders ORDER BY path")]

    def add_watched_folder(self, folder):
        """Запоминает папку. Вложенную в уже известную не дублируем,
        а известные вложенные в новую - заменяем ею."""
        folder = os.path.normpath(os.path.abspath(folder))
        current = self.get_folders()
        if any(is_inside(folder, f) for f in current):
            return
        for f in current:
            if is_inside(f, folder):
                self.conn.execute("DELETE FROM folders WHERE path = ?", (f,))
        self.conn.execute("INSERT OR IGNORE INTO folders (path) VALUES (?)", (folder,))
        self.conn.commit()

    def remove_watched_folder(self, folder, remove_files=False):
        """Перестать следить за папкой; remove_files - ещё и убрать её файлы из библиотеки."""
        self.conn.execute("DELETE FROM folders WHERE path = ?", (folder,))
        removed = 0
        if remove_files:
            ids = [r["id"] for r in self.conn.execute("SELECT id, path FROM files").fetchall()
                   if is_inside(r["path"], folder)]
            removed = self.remove_files(ids, hide=False)  # папку не отслеживаем - скрывать незачем
        self.conn.commit()
        return removed

    # ================= файлы =================
    def add_file(self, path, auto_tag=True):
        """Добавляет файл в базу. Возвращает True, если он новый."""
        p = Path(os.path.abspath(path))  # всегда полный путь - иначе один файл попадёт дважды
        ext = p.suffix.lower()
        info = stat_info(str(p))
        size, mtime, dev, inode = info if info else (0, 0, "", "")
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO files (path, name, ext, size, mtime, dev, inode) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(p), p.name, ext, size, mtime, dev, inode),
        )
        is_new = cur.rowcount == 1
        if is_new and auto_tag:
            self._auto_tag_file(cur.lastrowid, ext)
            self._apply_rules_to(cur.lastrowid, str(p))
        return is_new

    def add_folder(self, folder):
        """Добавляет все файлы папки (с вложенными) и начинает за ней следить.
        Возвращает число новых."""
        from app.safety import walk_files  # noqa: PLC0415
        folder = os.path.abspath(folder)
        self.add_watched_folder(folder)
        new_count, batch = 0, []
        for path, _entry in walk_files(folder):
            batch.append((path, stat_info(path)))
            if len(batch) >= 2000:
                new_count += self.add_files_bulk(batch)
                batch = []
        new_count += self.add_files_bulk(batch)
        return new_count

    def add_files_bulk(self, items):
        """Быстрое добавление пачки файлов одной транзакцией.
        items: [(путь, stat_info)] -> сколько новых. Авто-теги и правила ставятся сразу."""
        hidden = self.hidden_keys()
        rules = self.conn.execute("SELECT tag_id, kind, value FROM auto_rules WHERE enabled = 1").fetchall()
        auto_ids = {}
        added = 0
        with self.conn:  # одна транзакция на всю пачку
            for path, info in items:
                path = os.path.abspath(path)
                if os.path.normcase(path) in hidden or is_ignored(path):
                    continue
                size, mtime, dev, inode = info or (0, 0, "", "")
                name = os.path.basename(path)
                ext = os.path.splitext(name)[1].lower()
                cur = self.conn.execute(
                    "INSERT OR IGNORE INTO files (path, name, ext, size, mtime, dev, inode) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)", (path, name, ext, size, mtime, dev, inode))
                if cur.rowcount != 1:
                    continue
                added += 1
                fid = cur.lastrowid
                auto = EXT_TO_AUTO.get(ext)
                if auto:
                    if auto not in auto_ids:
                        auto_ids[auto] = self._ensure_tag(auto, AUTO_TAGS[auto][0], is_auto=1, grp=AUTO_GROUP)
                        self.conn.execute("UPDATE tags SET icon = ? WHERE id = ? AND (icon IS NULL OR icon = '')",
                                          (AUTO_ICONS.get(auto, ""), auto_ids[auto]))
                    self.conn.execute("INSERT OR IGNORE INTO file_tags (file_id, tag_id) VALUES (?, ?)",
                                      (fid, auto_ids[auto]))
                if rules:
                    self._apply_rules_to(fid, path, rules)
        return added

    # ---------- статус файла на диске ----------
    def all_paths(self):
        """[(id, путь)] - для фоновой проверки."""
        return [(r["id"], r["path"]) for r in self.conn.execute("SELECT id, path FROM files")]

    def update_file_stat(self, file_id, info):
        """Файл на месте: обновляем размер/время/номер и снимаем отметку "пропал".
        Возвращает True, если файл до этого считался пропавшим."""
        size, mtime, dev, inode = info
        row = self.conn.execute(
            "SELECT size, mtime, dev, inode, missing_since FROM files WHERE id = ?", (file_id,)
        ).fetchone()
        if row is None:
            return False
        # пишем в базу только если что-то поменялось: иначе, если база лежит
        # в отслеживаемой папке, каждая запись будила бы слежение снова и снова
        if (row["size"], row["mtime"], row["dev"], row["inode"]) != (size, mtime, dev, inode) \
                or row["missing_since"] is not None:
            changed = (row["size"], row["mtime"]) != (size, mtime)
            self.conn.execute(
                "UPDATE files SET size = ?, mtime = ?, dev = ?, inode = ?, missing_since = NULL"
                + (", qhash = NULL, fhash = NULL" if changed else "")  # содержимое могло измениться
                + " WHERE id = ?",
                (size, mtime, dev, inode, file_id),
            )
        return row["missing_since"] is not None

    def mark_missing(self, file_id):
        """Возвращает True, если отметка поставлена только что."""
        cur = self.conn.execute(
            "UPDATE files SET missing_since = datetime('now') "
            "WHERE id = ? AND missing_since IS NULL",
            (file_id,),
        )
        return cur.rowcount == 1

    def move_candidates(self, name, info):
        """Записи, которые могли бы быть этим файлом до перемещения (по убыванию уверенности)."""
        size, mtime, dev, inode = info
        found = []
        if inode:
            found += self.conn.execute(
                "SELECT *, 3 AS score FROM files WHERE dev = ? AND inode = ? "
                "AND (size = ? OR name = ?)",
                (dev, inode, size, name),
            ).fetchall()
        if size > 0:
            found += self.conn.execute(
                "SELECT *, 2 AS score FROM files WHERE name = ? AND size = ?", (name, size)
            ).fetchall()
            found += self.conn.execute(
                "SELECT *, 1 AS score FROM files WHERE size = ? AND ABS(mtime - ?) < 2",
                (size, mtime),
            ).fetchall()
        return found

    def relink(self, file_id, new_path, info=None):
        """Файл переехал: меняем путь, теги/коллекции/избранное остаются.

        Если по новому пути в базе уже есть другая запись (файл добавился как новый),
        переносим в неё теги/коллекции/★ и удаляем старую. Возвращает id итоговой записи."""
        new_path = str(Path(os.path.abspath(new_path)))
        p = Path(new_path)
        info = info or stat_info(new_path) or (0, 0, "", "")
        other = self.conn.execute(
            "SELECT id, favorite FROM files WHERE path = ? AND id <> ?", (new_path, file_id)
        ).fetchone()
        if other is not None:
            target = other["id"]
            self.conn.execute(
                "INSERT OR IGNORE INTO file_tags (file_id, tag_id) "
                "SELECT ?, tag_id FROM file_tags WHERE file_id = ?", (target, file_id))
            self.conn.execute(
                "INSERT OR IGNORE INTO file_collections (file_id, collection_id) "
                "SELECT ?, collection_id FROM file_collections WHERE file_id = ?", (target, file_id))
            self.conn.execute(
                "UPDATE files SET favorite = MAX(favorite, "
                "(SELECT favorite FROM files WHERE id = ?)) WHERE id = ?", (file_id, target))
            self.conn.execute("DELETE FROM files WHERE id = ?", (file_id,))
            file_id = target
        size, mtime, dev, inode = info
        self.conn.execute(
            "UPDATE files SET path = ?, name = ?, ext = ?, "
            "qhash = CASE WHEN size = ? AND mtime = ? THEN qhash ELSE NULL END, "
            "fhash = CASE WHEN size = ? AND mtime = ? THEN fhash ELSE NULL END, "
            "size = ?, mtime = ?, dev = ?, inode = ?, missing_since = NULL WHERE id = ?",
            (new_path, p.name, p.suffix.lower(), size, mtime, size, mtime,
             size, mtime, dev, inode, file_id),
        )
        self.conn.execute("DELETE FROM hidden_paths WHERE path = ?", (os.path.normcase(new_path),))
        self._auto_tag_file(file_id, p.suffix.lower())
        self._apply_rules_to(file_id, new_path)
        self.conn.commit()
        return file_id

    def remove_files(self, file_ids, hide=True):
        """Убирает файлы ИЗ БИБЛИОТЕКИ (с диска ничего не удаляется).

        hide=True - запомнить путь, чтобы слежение за папками не добавило файл снова.
        """
        ids = list(file_ids)
        if hide:
            for f in self.get_files(ids):
                self.conn.execute("INSERT OR IGNORE INTO hidden_paths (path) VALUES (?)",
                                  (os.path.normcase(f["path"]),))
        self.conn.executemany("DELETE FROM files WHERE id = ?", [(i,) for i in ids])
        self.conn.commit()
        return len(ids)

    def hidden_keys(self):
        return {r["path"] for r in self.conn.execute("SELECT path FROM hidden_paths")}

    def is_hidden(self, path):
        return self.conn.execute("SELECT 1 FROM hidden_paths WHERE path = ?",
                                 (os.path.normcase(os.path.abspath(path)),)).fetchone() is not None

    def unhide_all(self):
        n = self.conn.execute("DELETE FROM hidden_paths").rowcount
        self.conn.commit()
        return n

    # ---------- оценка, заметка, «недавние» ----------
    def set_rating(self, file_ids, rating):
        ids = [file_ids] if isinstance(file_ids, int) else list(file_ids)
        rating = max(0, min(5, int(rating)))
        self.conn.executemany("UPDATE files SET rating = ? WHERE id = ?", [(rating, i) for i in ids])
        self.conn.commit()

    def set_note(self, file_id, text):
        self.conn.execute("UPDATE files SET note = ? WHERE id = ?", (text, file_id))
        self.conn.commit()

    def mark_opened(self, file_id):
        self.conn.execute("UPDATE files SET last_opened = datetime('now') WHERE id = ?", (file_id,))
        self.conn.commit()

    def mark_opened_path(self, path):
        self.conn.execute("UPDATE files SET last_opened = datetime('now') WHERE path = ?",
                          (str(Path(os.path.abspath(path))),))
        self.conn.commit()

    def clear_recent(self):
        self.conn.execute("UPDATE files SET last_opened = NULL")
        self.conn.commit()

    # ---------- цвета картинок ----------
    def images_without_colors(self, exts, limit=400):
        marks = ",".join("?" * len(exts))
        return self.conn.execute(
            f"SELECT id, path FROM files WHERE colors IS NULL AND missing_since IS NULL "
            f"AND ext IN ({marks}) LIMIT ?", [*exts, limit]).fetchall()

    def set_colors(self, updates):
        """updates: {id: "красный,синий"} ('' - посчитали, ярких цветов нет)."""
        self.conn.executemany("UPDATE files SET colors = ? WHERE id = ?",
                              [(c, fid) for fid, c in updates.items()])
        self.conn.commit()

    # ---------- настройки и история поиска ----------
    def get_setting(self, key, default=None):
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set_setting(self, key, value):
        self.conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                          (key, json.dumps(value, ensure_ascii=False)))
        self.conn.commit()

    def push_search_history(self, text, keep=15):
        text = text.strip()
        if not text:
            return
        hist = [h for h in self.get_setting("search_history", []) if h != text]
        self.set_setting("search_history", [text, *hist][:keep])

    # ---------- значки тегов ----------
    def set_tag_icon(self, tag_id, symbol):
        self.conn.execute("UPDATE tags SET icon = ? WHERE id = ?", (symbol.strip(), tag_id))
        self.conn.commit()

    def set_tag_icon_image(self, tag_id, filename):
        self.conn.execute("UPDATE tags SET icon_image = ? WHERE id = ?", (filename or "", tag_id))
        self.conn.commit()

    # ---------- статистика ----------
    def stats(self):
        q = lambda sql, *p: self.conn.execute(sql, p).fetchone()[0]  # noqa: E731
        by_type = self.conn.execute(
            "SELECT t.name, t.color, t.icon, COUNT(*) AS n, COALESCE(SUM(f.size), 0) AS size "
            "FROM tags t JOIN file_tags ft ON ft.tag_id = t.id JOIN files f ON f.id = ft.file_id "
            "WHERE t.is_auto = 1 GROUP BY t.id ORDER BY size DESC").fetchall()
        top_tags = self.conn.execute(
            "SELECT t.name, t.color, COUNT(*) AS n FROM tags t JOIN file_tags ft ON ft.tag_id = t.id "
            "WHERE t.is_auto = 0 GROUP BY t.id ORDER BY n DESC LIMIT 10").fetchall()
        biggest = self.conn.execute(
            "SELECT name, path, size FROM files ORDER BY size DESC LIMIT 10").fetchall()
        by_month = self.conn.execute(
            "SELECT substr(added_at, 1, 7) AS month, COUNT(*) AS n FROM files "
            "GROUP BY month ORDER BY month DESC LIMIT 12").fetchall()
        groups, extra, wasted = self.duplicate_stats()
        return {
            "files": q("SELECT COUNT(*) FROM files"),
            "size": q("SELECT COALESCE(SUM(size), 0) FROM files"),
            "tags": q("SELECT COUNT(*) FROM tags WHERE is_auto = 0"),
            "collections": q("SELECT COUNT(*) FROM collections"),
            "folders": q("SELECT COUNT(*) FROM folders"),
            "tagged": q("SELECT COUNT(DISTINCT ft.file_id) FROM file_tags ft "
                        "JOIN tags t ON t.id = ft.tag_id WHERE t.is_auto = 0"),
            "favorites": q("SELECT COUNT(*) FROM files WHERE favorite = 1"),
            "rated": q("SELECT COUNT(*) FROM files WHERE rating > 0"),
            "noted": q("SELECT COUNT(*) FROM files WHERE note <> ''"),
            "missing": q("SELECT COUNT(*) FROM files WHERE missing_since IS NOT NULL"),
            "dup_groups": groups, "dup_extra": extra, "dup_wasted": wasted,
            "by_type": by_type, "top_tags": top_tags, "biggest": biggest,
            "by_month": list(reversed(by_month)),
        }

    # ---------- дубликаты ----------
    def dup_candidates(self):
        """Файлы на месте, у которых есть хотя бы один файл того же размера (> 0).
        Только среди них имеет смысл считать отпечатки."""
        return self.conn.execute(
            "SELECT id, path, size, qhash, fhash FROM files f "
            "WHERE f.missing_since IS NULL AND f.size > 0 AND f.size IN ("
            "  SELECT size FROM files WHERE missing_since IS NULL AND size > 0 "
            "  GROUP BY size HAVING COUNT(*) > 1) ORDER BY size"
        ).fetchall()

    def save_hashes(self, updates):
        """updates: {id: (qhash, fhash)}."""
        self.conn.executemany(
            "UPDATE files SET qhash = ?, fhash = COALESCE(?, fhash) WHERE id = ?",
            [(q, fh, fid) for fid, (q, fh) in updates.items()],
        )
        self.conn.commit()

    def copies_of(self, file_id):
        """Другие файлы библиотеки с тем же содержимым."""
        row = self.conn.execute("SELECT fhash FROM files WHERE id = ?", (file_id,)).fetchone()
        if row is None or row["fhash"] is None:
            return []
        return self.conn.execute(
            "SELECT * FROM files WHERE fhash = ? AND id <> ? AND missing_since IS NULL ORDER BY path",
            (row["fhash"], file_id),
        ).fetchall()

    def duplicate_stats(self):
        """(сколько групп, сколько лишних копий, сколько места они занимают)."""
        row = self.conn.execute(
            "SELECT COUNT(*) AS groups, COALESCE(SUM(n - 1), 0) AS extra, "
            "COALESCE(SUM((n - 1) * size), 0) AS wasted FROM ("
            "  SELECT fhash, COUNT(*) AS n, MAX(size) AS size FROM files "
            "  WHERE fhash IS NOT NULL AND missing_since IS NULL GROUP BY fhash HAVING n > 1)"
        ).fetchone()
        return row["groups"], row["extra"], row["wasted"]

    def merge_copy_tags(self, file_ids):
        """Все копии получают общие теги, коллекции и ★ (объединение)."""
        ids = list(file_ids)
        marks = ",".join("?" * len(ids))
        tags = [r[0] for r in self.conn.execute(
            f"SELECT DISTINCT tag_id FROM file_tags WHERE file_id IN ({marks})", ids)]
        cols = [r[0] for r in self.conn.execute(
            f"SELECT DISTINCT collection_id FROM file_collections WHERE file_id IN ({marks})", ids)]
        fav = self.conn.execute(f"SELECT MAX(favorite) FROM files WHERE id IN ({marks})", ids).fetchone()[0]
        for fid in ids:
            self.conn.executemany("INSERT OR IGNORE INTO file_tags (file_id, tag_id) VALUES (?, ?)",
                                  [(fid, t) for t in tags])
            self.conn.executemany(
                "INSERT OR IGNORE INTO file_collections (file_id, collection_id) VALUES (?, ?)",
                [(fid, c) for c in cols])
        self.conn.execute(f"UPDATE files SET favorite = ? WHERE id IN ({marks})", [fav or 0, *ids])
        self.conn.commit()

    def missing_ids(self):
        return [r["id"] for r in self.conn.execute(
            "SELECT id FROM files WHERE missing_since IS NOT NULL")]

    def get_file(self, file_id):
        return self.conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()

    def get_files(self, file_ids):
        ids = list(file_ids)
        if not ids:
            return []
        return self.conn.execute(
            f"SELECT * FROM files WHERE id IN ({','.join('?' * len(ids))})", ids
        ).fetchall()

    def set_favorite(self, file_ids, value):
        """file_ids - один id или список."""
        ids = [file_ids] if isinstance(file_ids, int) else list(file_ids)
        self.conn.executemany(
            "UPDATE files SET favorite = ? WHERE id = ?", [(1 if value else 0, i) for i in ids]
        )
        self.conn.commit()

    # ---------- построение WHERE ----------
    @staticmethod
    def _tag_conditions(include, exclude, mode, where, params):
        """Тег в фильтре = он сам или любой вложенный в него (Животные -> Кошки, Собаки)."""
        include = list(dict.fromkeys(include))
        exclude = list(dict.fromkeys(exclude))
        if include:
            if mode == "any":
                where.append(query.has_tag_sql(f"id IN ({','.join('?' * len(include))})"))
                params.extend(include)
            else:
                for tid in include:
                    where.append(query.has_tag_sql("id = ?"))
                    params.append(tid)
        if exclude:
            where.append("NOT " + query.has_tag_sql(f"id IN ({','.join('?' * len(exclude))})"))
            params.extend(exclude)

    def _build_where(self, flt):
        where, params = [], []
        c = flt.collection
        if c is not None:
            if c["rules"] is None:  # обычная коллекция
                where.append(
                    "EXISTS (SELECT 1 FROM file_collections fc "
                    "WHERE fc.file_id = f.id AND fc.collection_id = ?)"
                )
                params.append(c["id"])
            else:  # динамическая: правила
                rules = c["rules"]
                self._tag_conditions(
                    rules.get("tags", []), rules.get("exclude_tags", []),
                    rules.get("tag_mode", "all"), where, params,
                )
                exts = rules.get("exts")
                if exts:
                    where.append(f"f.ext IN ({','.join('?' * len(exts))})")
                    params.extend(exts)
                if rules.get("min_kb"):
                    where.append("f.size >= ?")
                    params.append(rules["min_kb"] * 1024)
                if rules.get("days"):
                    where.append("f.added_at >= datetime('now', ?)")
                    params.append(f"-{int(rules['days'])} days")
                if rules.get("query"):  # сохранённый умный поиск
                    sql, p = query.to_sql(query.parse(rules["query"]))
                    if sql:
                        where.append(sql)
                        params.extend(p)
        if flt.favorites:
            where.append("f.favorite = 1")
        if flt.missing:
            where.append("f.missing_since IS NOT NULL")
        if flt.duplicates:
            where.append(DUP_SQL)
        if flt.recent:
            where.append("f.last_opened IS NOT NULL")
        if flt.folder:  # без LIKE: в путях бывают _ и %, которые LIKE понял бы как шаблон
            prefix = os.path.normcase(os.path.join(os.path.abspath(flt.folder), ""))
            where.append("substr(py_normcase(f.path), 1, ?) = ?")
            params.extend([len(prefix), prefix])
        if flt.no_auto_tags:
            where.append(
                "NOT EXISTS (SELECT 1 FROM file_tags x JOIN tags t ON t.id = x.tag_id "
                "WHERE x.file_id = f.id AND t.is_auto = 1)"
            )
        if flt.no_tags:
            where.append("NOT EXISTS (SELECT 1 FROM file_tags x WHERE x.file_id = f.id)")
        if flt.no_user_tags:
            where.append(
                "NOT EXISTS (SELECT 1 FROM file_tags x JOIN tags t ON t.id = x.tag_id "
                "WHERE x.file_id = f.id AND t.is_auto = 0)"
            )
        if flt.search:  # умный поиск: см. app/query.py
            sql, p = query.to_sql(query.parse(flt.search))
            if sql:
                where.append(sql)
                params.extend(p)
        self._tag_conditions(flt.include, flt.exclude, flt.mode, where, params)
        sql = (" WHERE " + " AND ".join(where)) if where else ""
        return sql, params

    SORTS = {
        "name": "py_lower(f.name)",
        "added": "f.added_at DESC, py_lower(f.name)",
        "size": "f.size DESC, py_lower(f.name)",
        "ext": "f.ext, py_lower(f.name)",
        "dups": "f.size DESC, f.fhash, py_lower(f.path)",  # копии стоят рядом
        "rating": "f.rating DESC, py_lower(f.name)",
        "recent": "f.last_opened DESC",
    }

    def query_files(self, flt=None, sort="name"):
        where_sql, params = self._build_where(flt or FileFilter())
        order = self.SORTS.get(sort, self.SORTS["name"])
        sql = (
            "SELECT f.*, "
            "(SELECT GROUP_CONCAT(t.name, ', ') FROM file_tags x "
            "JOIN tags t ON t.id = x.tag_id WHERE x.file_id = f.id) AS tags_text, "
            "(SELECT GROUP_CONCAT(t.color, ',') FROM file_tags x "
            "JOIN tags t ON t.id = x.tag_id WHERE x.file_id = f.id) AS tag_colors, "
            "(SELECT GROUP_CONCAT(x.tag_id, ',') FROM file_tags x WHERE x.file_id = f.id) AS tag_ids "
            "FROM files f" + where_sql + " ORDER BY " + order
        )
        return self.conn.execute(sql, params).fetchall()

    def count_files(self, flt=None):
        where_sql, params = self._build_where(flt or FileFilter())
        return self.conn.execute("SELECT COUNT(*) FROM files f" + where_sql, params).fetchone()[0]

    # ================= теги =================
    def _ensure_tag(self, name, color=None, is_auto=0, grp=""):
        row = self.conn.execute(
            "SELECT id FROM tags WHERE py_lower(name) = ?", (name.lower(),)
        ).fetchone()
        if row:
            return row["id"]
        if color is None:
            n = self.conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
            color = PALETTE[n % len(PALETTE)]
        cur = self.conn.execute(
            "INSERT INTO tags (name, color, is_auto, grp) VALUES (?, ?, ?, ?)",
            (name, color, is_auto, grp),
        )
        return cur.lastrowid

    def ensure_tag(self, name, color=None, grp=""):
        """Возвращает id тега, создавая его при необходимости."""
        name = name.strip()
        if not name:
            return None
        tag_id = self._ensure_tag(name, color, grp=grp.strip())
        self.conn.commit()
        return tag_id

    def get_tag(self, tag_id):
        return self.conn.execute("SELECT * FROM tags WHERE id = ?", (tag_id,)).fetchone()

    def get_tags_with_counts(self):
        """Теги, самые популярные первыми (как в Steam). cnt - сколько файлов всего."""
        return self.conn.execute(
            "SELECT t.*, COUNT(ft.file_id) AS cnt FROM tags t "
            "LEFT JOIN file_tags ft ON ft.tag_id = t.id "
            "GROUP BY t.id ORDER BY cnt DESC, t.name COLLATE NOCASE"
        ).fetchall()

    def tag_facets(self, flt):
        """Счётчики для плашек-фильтров, как в магазине Steam.

        cnt - сколько файлов с этим тегом среди найденных сейчас.
        В режиме И это ровно "сколько останется, если добавить этот тег".
        В режиме ИЛИ считаем без учёта нужных тегов, иначе остальные
        варианты "или" обнулились бы и пропали.
        """
        if flt.mode == "any":
            flt = FileFilter(**{**flt.__dict__, "include": ()})
        where_sql, params = self._build_where(flt)
        # считаем в Python: файл с «Кошки» засчитывается и тегу «Животные»
        file_tags = {}
        for r in self.conn.execute(
            f"SELECT file_id, tag_id FROM file_tags WHERE file_id IN (SELECT f.id FROM files f{where_sql})",
            params,
        ):
            file_tags.setdefault(r["file_id"], set()).add(r["tag_id"])
        anc = self.ancestors_map()
        counts = {}
        for tags in file_tags.values():
            implied = set()
            for t in tags:
                implied |= anc.get(t, {t})
            for t in implied:
                counts[t] = counts.get(t, 0) + 1
        rows = [Facet(dict(t), counts.get(t["id"], 0)) for t in
                self.conn.execute("SELECT * FROM tags").fetchall()]
        rows.sort(key=lambda r: (-r["cnt"], r["name"].lower()))
        return rows

    # ---------- вложенные теги ----------
    def parent_map(self):
        return {r["id"]: r["parent_id"] for r in self.conn.execute("SELECT id, parent_id FROM tags")}

    def ancestors_map(self):
        """{id тега: {он сам и все его родители}}."""
        parents = self.parent_map()
        result = {}
        for tid in parents:
            chain, cur = set(), tid
            while cur is not None and cur not in chain:  # защита от петель
                chain.add(cur)
                cur = parents.get(cur)
            result[tid] = chain
        return result

    def descendants(self, tag_id):
        """Все вложенные теги (любой глубины), без самого тега."""
        children = {}
        for tid, pid in self.parent_map().items():
            children.setdefault(pid, []).append(tid)
        out, stack = set(), list(children.get(tag_id, []))
        while stack:
            t = stack.pop()
            if t not in out:
                out.add(t)
                stack.extend(children.get(t, []))
        return out

    def tag_paths(self):
        """{id: "Животные › Кошки"} - полный путь тега для подсказок."""
        rows = {r["id"]: r for r in self.conn.execute("SELECT id, name, parent_id FROM tags")}
        paths = {}
        for tid in rows:
            names, cur, seen = [], tid, set()
            while cur is not None and cur in rows and cur not in seen:
                seen.add(cur)
                names.append(rows[cur]["name"])
                cur = rows[cur]["parent_id"]
            paths[tid] = " › ".join(reversed(names))
        return paths

    def tag_depths(self):
        return {tid: p.count(" › ") for tid, p in self.tag_paths().items()}

    def set_parent(self, tag_id, parent_id):
        """Вкладывает тег в другой. False, если получится петля (тег внутрь самого себя)."""
        if parent_id is not None and (parent_id == tag_id or parent_id in self.descendants(tag_id)):
            return False
        self.conn.execute("UPDATE tags SET parent_id = ? WHERE id = ?", (parent_id, tag_id))
        self.conn.commit()
        return True

    def get_children(self, tag_id):
        return self.conn.execute(
            "SELECT * FROM tags WHERE parent_id = ? ORDER BY name COLLATE NOCASE", (tag_id,)
        ).fetchall()

    def get_groups(self):
        rows = self.conn.execute(
            "SELECT DISTINCT grp FROM tags WHERE grp <> '' ORDER BY grp COLLATE NOCASE"
        ).fetchall()
        return [r["grp"] for r in rows]

    def get_file_tags(self, file_id):
        return self.conn.execute(
            "SELECT t.* FROM tags t JOIN file_tags ft ON ft.tag_id = t.id "
            "WHERE ft.file_id = ? ORDER BY t.is_auto DESC, t.name COLLATE NOCASE",
            (file_id,),
        ).fetchall()

    def get_tags_for_files(self, file_ids):
        """Теги выделенных файлов: [(тег, сколько из выделенных файлов его имеют)]."""
        ids = list(file_ids)
        if not ids:
            return []
        rows = self.conn.execute(
            "SELECT t.*, COUNT(*) AS cnt FROM tags t JOIN file_tags ft ON ft.tag_id = t.id "
            f"WHERE ft.file_id IN ({','.join('?' * len(ids))}) "
            "GROUP BY t.id ORDER BY t.is_auto DESC, cnt DESC, t.name COLLATE NOCASE",
            ids,
        ).fetchall()
        return rows

    def rename_tag(self, tag_id, new_name):
        new_name = new_name.strip()
        clash = self.conn.execute(
            "SELECT id FROM tags WHERE py_lower(name) = ? AND id <> ?",
            (new_name.lower(), tag_id),
        ).fetchone()
        if not new_name or clash:
            return False
        self.conn.execute("UPDATE tags SET name = ? WHERE id = ?", (new_name, tag_id))
        self.conn.commit()
        return True

    def set_tag_color(self, tag_id, color):
        self.conn.execute("UPDATE tags SET color = ? WHERE id = ?", (color, tag_id))
        self.conn.commit()

    def set_tag_group(self, tag_ids, grp):
        ids = [tag_ids] if isinstance(tag_ids, int) else list(tag_ids)
        self.conn.executemany(
            "UPDATE tags SET grp = ? WHERE id = ?", [(grp.strip(), i) for i in ids]
        )
        self.conn.commit()

    def delete_tag(self, tag_id):
        # вложенные теги не теряются: поднимаются на уровень выше
        row = self.conn.execute("SELECT parent_id FROM tags WHERE id = ?", (tag_id,)).fetchone()
        if row is not None:
            self.conn.execute("UPDATE tags SET parent_id = ? WHERE parent_id = ?", (row["parent_id"], tag_id))
        self.conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
        self._rewrite_rule_tags({tag_id: None})
        self.conn.commit()

    def merge_tags(self, source_ids, target_id):
        """Сливает теги в один: файлы получают target, исходные теги удаляются."""
        sources = [s for s in source_ids if s != target_id]
        for sid in sources:
            self.conn.execute(
                "INSERT OR IGNORE INTO file_tags (file_id, tag_id) "
                "SELECT file_id, ? FROM file_tags WHERE tag_id = ?",
                (target_id, sid),
            )
            # вложенные теги исходного переезжают в целевой
            self.conn.execute("UPDATE tags SET parent_id = ? WHERE parent_id = ? AND id <> ?",
                              (target_id, sid, target_id))
            # если целевой сам был вложен в исходный - поднимаем его, чтобы не было петли
            self.conn.execute("UPDATE tags SET parent_id = (SELECT parent_id FROM tags WHERE id = ?) "
                              "WHERE id = ? AND parent_id = ?", (sid, target_id, sid))
            self.conn.execute("DELETE FROM tags WHERE id = ?", (sid,))
        self._rewrite_rule_tags({sid: target_id for sid in sources})
        self.conn.commit()

    def _rewrite_rule_tags(self, mapping):
        """Правит правила динамических коллекций после удаления/слияния тегов."""
        for c in self.get_collections():
            rules = c["rules"]
            if not rules:
                continue
            changed = False
            for key in ("tags", "exclude_tags"):
                old = rules.get(key, [])
                new = []
                for tid in old:
                    tid = mapping.get(tid, tid)
                    if tid is not None and tid not in new:
                        new.append(tid)
                if new != old:
                    changed = True
                    if new:
                        rules[key] = new
                    else:
                        rules.pop(key, None)
            if changed:
                self.conn.execute(
                    "UPDATE collections SET rules = ? WHERE id = ?", (json.dumps(rules), c["id"])
                )

    def tag_file(self, file_id, tag_id):
        self.tag_files([file_id], tag_id)

    def untag_file(self, file_id, tag_id):
        self.untag_files([file_id], tag_id)

    def tag_files(self, file_ids, tag_id):
        self.conn.executemany(
            "INSERT OR IGNORE INTO file_tags (file_id, tag_id) VALUES (?, ?)",
            [(fid, tag_id) for fid in file_ids],
        )
        self.conn.commit()

    def untag_files(self, file_ids, tag_id):
        self.conn.executemany(
            "DELETE FROM file_tags WHERE file_id = ? AND tag_id = ?",
            [(fid, tag_id) for fid in file_ids],
        )
        self.conn.commit()

    # ---------- авто-теги ----------
    def _auto_tag_file(self, file_id, ext):
        name = EXT_TO_AUTO.get(ext)
        if not name:
            return
        color = AUTO_TAGS[name][0]
        tag_id = self._ensure_tag(name, color, is_auto=1, grp=AUTO_GROUP)
        self.conn.execute("UPDATE tags SET icon = ? WHERE id = ? AND (icon IS NULL OR icon = '')",
                          (AUTO_ICONS.get(name, ""), tag_id))
        self.conn.execute(
            "INSERT OR IGNORE INTO file_tags (file_id, tag_id) VALUES (?, ?)",
            (file_id, tag_id),
        )

    def apply_auto_tags(self):
        """Проставляет авто-теги по расширению всем файлам в базе."""
        for row in self.conn.execute("SELECT id, ext FROM files").fetchall():
            self._auto_tag_file(row["id"], row["ext"])
        self.conn.commit()

    # ================= правила авто-тегов =================
    RULE_KINDS = {
        "folder": "лежит в папке",
        "name": "имя файла",
        "ext": "расширение",
        "path": "путь содержит",
    }

    @staticmethod
    def rule_matches(path, kind, value):
        value = value.strip().lower()
        if not value:
            return False
        p = path.lower()
        if kind == "folder":
            parts = [x for x in Path(p).parts[:-1]]
            return value in parts
        if kind == "name":
            name = os.path.basename(p)
            return fnmatch.fnmatch(name, value) if any(c in value for c in "*?[") else value in name
        if kind == "ext":
            exts = {e if e.startswith(".") else "." + e for e in value.replace(",", " ").split()}
            return os.path.splitext(p)[1] in exts
        if kind == "path":
            return value in p
        return False

    def get_rules(self):
        return self.conn.execute(
            "SELECT r.*, t.name AS tag_name, t.color AS tag_color FROM auto_rules r "
            "JOIN tags t ON t.id = r.tag_id ORDER BY t.name COLLATE NOCASE, r.id"
        ).fetchall()

    def add_rule(self, tag_id, kind, value):
        value = value.strip()
        if not value or kind not in self.RULE_KINDS:
            return None
        row = self.conn.execute(
            "SELECT id FROM auto_rules WHERE tag_id = ? AND kind = ? AND py_lower(value) = ?",
            (tag_id, kind, value.lower()),
        ).fetchone()
        if row:
            return row["id"]
        cur = self.conn.execute(
            "INSERT INTO auto_rules (tag_id, kind, value) VALUES (?, ?, ?)", (tag_id, kind, value)
        )
        self.conn.commit()
        return cur.lastrowid

    def set_rule_enabled(self, rule_id, enabled):
        self.conn.execute("UPDATE auto_rules SET enabled = ? WHERE id = ?", (1 if enabled else 0, rule_id))
        self.conn.commit()

    def delete_rule(self, rule_id):
        self.conn.execute("DELETE FROM auto_rules WHERE id = ?", (rule_id,))
        self.conn.commit()

    def _apply_rules_to(self, file_id, path, rules=None):
        added = 0
        rules = rules if rules is not None else self.conn.execute(
            "SELECT tag_id, kind, value FROM auto_rules WHERE enabled = 1").fetchall()
        for r in rules:
            if self.rule_matches(path, r["kind"], r["value"]):
                cur = self.conn.execute(
                    "INSERT OR IGNORE INTO file_tags (file_id, tag_id) VALUES (?, ?)",
                    (file_id, r["tag_id"]),
                )
                added += cur.rowcount
        return added

    def apply_rules_all(self, rule_ids=None):
        """Прогоняет правила по всей библиотеке. Возвращает, сколько тегов поставлено."""
        sql = "SELECT tag_id, kind, value FROM auto_rules WHERE enabled = 1"
        params = []
        if rule_ids:
            sql += f" AND id IN ({','.join('?' * len(rule_ids))})"
            params = list(rule_ids)
        rules = self.conn.execute(sql, params).fetchall()
        added = 0
        if rules:
            for row in self.conn.execute("SELECT id, path FROM files").fetchall():
                added += self._apply_rules_to(row["id"], row["path"], rules)
        self.conn.commit()
        return added

    def rule_preview_count(self, kind, value):
        """Сколько файлов библиотеки подходит под правило (для подсказки в окне)."""
        return sum(1 for (p,) in self.conn.execute("SELECT path FROM files")
                   if self.rule_matches(p, kind, value))

    def folder_name_stats(self):
        """Имена папок внутри папок библиотеки и сколько файлов в каждой (для «Папки → теги»).
        [(имя папки, файлов)] - самые большие первыми."""
        roots = self.get_folders()
        counts = {}
        for (p,) in self.conn.execute("SELECT path FROM files"):
            root = next((r for r in roots if is_inside(p, r)), None)
            rel_dirs = Path(os.path.relpath(p, root)).parts[:-1] if root else ()
            for name in set(rel_dirs):
                key = name.lower()
                shown, n = counts.get(key, (name, 0))
                counts[key] = (shown, n + 1)
        return sorted(counts.values(), key=lambda x: (-x[1], x[0].lower()))

    def folder_parents(self):
        """{имя папки (lower): имя папки, в которой она лежит чаще всего} - чтобы
        «Папки → теги» повторил вложенность: Школа/Математика -> тег Математика внутри Школа."""
        roots = self.get_folders()
        pairs = {}
        for (p,) in self.conn.execute("SELECT path FROM files"):
            root = next((r for r in roots if is_inside(p, r)), None)
            if not root:
                continue
            parts = Path(os.path.relpath(p, root)).parts[:-1]
            for parent, child in zip(parts, parts[1:], strict=False):  # соседние пары
                key = (child.lower(), parent)
                pairs[key] = pairs.get(key, 0) + 1
        best = {}
        for (child, parent), n in pairs.items():
            if child not in best or n > best[child][1]:
                best[child] = (parent, n)
        return {child: parent for child, (parent, _n) in best.items()}

    # ================= коллекции =================
    def get_collections(self):
        result = []
        for r in self.conn.execute("SELECT * FROM collections ORDER BY name COLLATE NOCASE"):
            rules = json.loads(r["rules"]) if r["rules"] is not None else None
            result.append({"id": r["id"], "name": r["name"], "rules": rules})
        return result

    def create_collection(self, name, rules=None):
        """rules=None -> обычная коллекция, dict -> динамическая. None, если имя занято."""
        name = name.strip()
        if not name or self._collection_name_taken(name):
            return None
        cur = self.conn.execute(
            "INSERT INTO collections (name, rules) VALUES (?, ?)",
            (name, json.dumps(rules) if rules is not None else None),
        )
        self.conn.commit()
        return cur.lastrowid

    def _collection_name_taken(self, name, except_id=None):
        row = self.conn.execute(
            "SELECT id FROM collections WHERE py_lower(name) = ? AND id <> ?",
            (name.lower(), except_id if except_id is not None else -1),
        ).fetchone()
        return row is not None

    def rename_collection(self, collection_id, name):
        name = name.strip()
        if not name or self._collection_name_taken(name, collection_id):
            return False
        self.conn.execute("UPDATE collections SET name = ? WHERE id = ?", (name, collection_id))
        self.conn.commit()
        return True

    def update_collection_rules(self, collection_id, rules):
        self.conn.execute(
            "UPDATE collections SET rules = ? WHERE id = ?", (json.dumps(rules), collection_id)
        )
        self.conn.commit()

    def delete_collection(self, collection_id):
        self.conn.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
        self.conn.commit()

    def add_to_collection(self, file_ids, collection_id):
        ids = [file_ids] if isinstance(file_ids, int) else list(file_ids)
        self.conn.executemany(
            # SELECT из files: если файл успели удалить из базы - просто пропускаем
            "INSERT OR IGNORE INTO file_collections (file_id, collection_id) "
            "SELECT id, ? FROM files WHERE id = ?",
            [(collection_id, i) for i in ids],
        )
        self.conn.commit()

    def remove_from_collection(self, file_ids, collection_id):
        ids = [file_ids] if isinstance(file_ids, int) else list(file_ids)
        self.conn.executemany(
            "DELETE FROM file_collections WHERE file_id = ? AND collection_id = ?",
            [(i, collection_id) for i in ids],
        )
        self.conn.commit()

    def get_file_collection_ids(self, file_id):
        rows = self.conn.execute(
            "SELECT collection_id FROM file_collections WHERE file_id = ?", (file_id,)
        ).fetchall()
        return {r["collection_id"] for r in rows}

    def collection_counts_for_files(self, file_ids):
        """{id коллекции: сколько из выделенных файлов в ней лежит}."""
        ids = list(file_ids)
        if not ids:
            return {}
        rows = self.conn.execute(
            "SELECT collection_id, COUNT(*) AS cnt FROM file_collections "
            f"WHERE file_id IN ({','.join('?' * len(ids))}) GROUP BY collection_id",
            ids,
        ).fetchall()
        return {r["collection_id"]: r["cnt"] for r in rows}
