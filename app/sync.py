"""Сверка библиотеки с диском: какие файлы пропали, какие переехали, какие появились.

Работает в два шага, чтобы окно не зависало:
  1. collect() - только диск (os.stat / обход папок). Безопасно звать в фоновом потоке.
  2. apply()   - только база. Зовём в главном потоке с результатом collect().

Как узнаём, что файл ПЕРЕЕХАЛ, а не "один пропал, другой появился"
(в порядке уверенности):
  3 - тот же номер файла на диске (st_dev + st_ino; на NTFS не меняется при перемещении
      и переименовании в пределах диска) + совпадает размер или имя;
  2 - то же имя и размер;
  1 - тот же размер и время изменения (переименовали и перенесли на другой диск).
Подходит только запись, у которой старого файла на диске уже нет (иначе это копия).
Найденный файл получает путь старой записи, а теги, коллекции и ★ остаются.

Записи о пропавших файлах НЕ удаляются: им ставится отметка "потерян".
Это важно для флешек и сетевых дисков: вставил обратно - всё вернулось.
"""
import hashlib
import os
from dataclasses import dataclass, field

from app.db import is_ignored, is_inside, stat_info
from app.safety import skip_dir


@dataclass
class Snapshot:
    known: dict = field(default_factory=dict)  # id -> stat_info или None (нет на диске)
    disk: dict = field(default_factory=dict)   # путь -> stat_info для файлов, которых нет в базе
    dirs: list = field(default_factory=list)   # все папки внутри папок библиотеки (для слежения)
    full: bool = True


@dataclass
class Report:
    moved: int = 0       # нашлись на новом месте
    missing: int = 0     # пропали только что
    restored: int = 0    # снова на месте (вернули флешку и т.п.)
    added: int = 0       # новые файлы в папках библиотеки
    still_missing: int = 0
    moved_items: list = field(default_factory=list)   # [(старое имя, новое имя)] - для уведомления

    def text(self):
        parts = []
        if self.moved:
            parts.append(f"переехало {self.moved}")
        if self.restored:
            parts.append(f"вернулось {self.restored}")
        if self.added:
            parts.append(f"новых {self.added}")
        if self.missing:
            parts.append(f"пропало {self.missing}")
        if not parts:
            parts.append("изменений нет")
        tail = f"  ·  потерянных всего: {self.still_missing}" if self.still_missing else ""
        return "Проверка файлов: " + ", ".join(parts) + tail

    @property
    def changed(self):
        return bool(self.moved or self.missing or self.restored or self.added)


def _key(path):
    return os.path.normcase(os.path.abspath(path))


def collect(known_paths, roots, changed_dirs=None):
    """known_paths: [(id, путь)] из базы, roots: папки библиотеки.

    changed_dirs=None - полная проверка: каждый файл базы + обход всех папок.
    changed_dirs=[...] - быстрая: только эти папки (от слежения за папками).
    """
    snap = Snapshot(full=changed_dirs is None)
    known_keys = {_key(p) for _i, p in known_paths}
    known_dirs = {os.path.dirname(p) for _i, p in known_paths}

    def scan_dir(top, recursive):
        try:
            entries = list(os.scandir(top))
        except OSError:
            return
        snap.dirs.append(top)
        for e in entries:
            try:
                if e.is_dir(follow_symlinks=False):
                    if skip_dir(e) or is_ignored(os.path.join(e.path, "x")):
                        continue
                    # при быстрой проверке: подпапка без известных файлов - новая
                    # (например, в папку перенесли целую папку), проходим её целиком
                    is_new = not any(is_inside(d, e.path) for d in known_dirs)
                    if recursive or is_new:
                        scan_dir(e.path, True)
                    else:
                        snap.dirs.append(e.path)
                elif e.is_file(follow_symlinks=False):
                    if _key(e.path) in known_keys or is_ignored(e.path):
                        continue
                    info = stat_info(e.path)
                    if info:
                        snap.disk[e.path] = info
            except OSError:
                continue

    if changed_dirs is None:
        for fid, path in known_paths:
            snap.known[fid] = stat_info(path)
        for root in roots:
            scan_dir(root, True)
    else:
        changed = [os.path.normpath(d) for d in changed_dirs]
        for fid, path in known_paths:
            parent = os.path.dirname(path)
            for d in changed:
                # файл прямо в изменившейся папке, или папку целиком удалили/перенесли
                if _key(parent) == _key(d) or (not os.path.isdir(d) and is_inside(path, d)):
                    snap.known[fid] = stat_info(path)
                    break
        for d in changed:
            if os.path.isdir(d):
                scan_dir(d, False)
    snap.dirs = list(dict.fromkeys(snap.dirs))
    return snap


def apply(db, snap):
    """Записывает результат collect() в базу. Возвращает Report."""
    rep = Report()
    gone = set()
    for fid, info in snap.known.items():
        if info is None:
            gone.add(fid)
        elif db.update_file_stat(fid, info):
            rep.restored += 1

    # файлы, которые пользователь убрал из библиотеки, не возвращаем
    hidden = db.hidden_keys()
    if hidden:
        snap.disk = {p: i for p, i in snap.disk.items() if _key(p) not in hidden}

    # сначала ищем, не переехал ли кто-то из пропавших
    stat_cache = {}

    def is_gone(c):
        """Старого файла на диске уже нет - иначе новый файл это копия, а не перемещение."""
        if c["id"] in gone or c["missing_since"] is not None:
            return True
        if c["id"] not in stat_cache:
            stat_cache[c["id"]] = stat_info(c["path"])
        return stat_cache[c["id"]] is None

    taken = set()
    new_files = []
    for path, info in sorted(snap.disk.items()):
        cands = [
            c for c in db.move_candidates(os.path.basename(path), info)
            if c["id"] not in taken and _key(c["path"]) != _key(path) and is_gone(c)
        ]
        best = None
        if cands:
            top = max(c["score"] for c in cands)
            ids = {c["id"] for c in cands if c["score"] == top}
            if len(ids) == 1:  # однозначно - иначе не гадаем, добавим как новый
                best = ids.pop()
        if best is not None:
            old = next(c["path"] for c in cands if c["id"] == best)
            rep.moved_items.append((os.path.basename(old), os.path.basename(path)))
            db.relink(best, path, info)
            taken.add(best)
            gone.discard(best)
            rep.moved += 1
        else:
            new_files.append(path)

    for fid in gone:
        if db.mark_missing(fid):
            rep.missing += 1

    for path in new_files:
        if db.add_file(path):
            rep.added += 1
    db.conn.commit()
    rep.still_missing = len(db.missing_ids())
    return rep


# ================= помощник для потерянного файла =================
def find_candidates(name, size, ext, search_dirs, known_paths=(), limit=30, max_dirs=20000):
    """Ищет, где может быть потерянный файл. Для фонового потока (только диск).

    TagStudio не умеет находить переименованные файлы, а при нескольких совпадениях
    просто сдаётся. Здесь показываем все варианты с причиной - выбирает человек.

    -> [(путь, размер, время изменения, оценка, причина)] - лучшие первыми.
    """
    import difflib

    stem = os.path.splitext(name)[0].lower()
    known = {_key(p) for p in known_paths}
    found, seen_dirs = [], 0
    for top in search_dirs:
        if not os.path.isdir(top):
            continue
        for root, dirs, files in os.walk(top):
            seen_dirs += 1
            if seen_dirs > max_dirs:
                break
            dirs[:] = [d for d in dirs if not skip_dir(os.path.join(root, d), d)
                       and not is_ignored(os.path.join(root, d, "x"))]
            for fn in files:
                path = os.path.join(root, fn)
                low = fn.lower()
                same_name = low == name.lower()
                same_ext = os.path.splitext(low)[1] == ext
                if not (same_name or same_ext):
                    continue
                info = None
                score, why = 0, []
                if same_name:
                    score += 50
                    why.append("то же имя")
                elif same_ext:
                    ratio = difflib.SequenceMatcher(None, stem, os.path.splitext(low)[0]).ratio()
                    if ratio >= 0.6:
                        score += int(ratio * 30)
                        why.append(f"похожее имя ({ratio:.0%})")
                if same_ext and score == 0:
                    info = stat_info(path)
                    if not info or info[0] != size or size == 0:
                        continue
                info = info or stat_info(path)
                if not info:
                    continue
                if size and info[0] == size:
                    score += 40
                    why.append("тот же размер")
                if score < 40:
                    continue
                if _key(path) in known:
                    why.append("уже в библиотеке - объединю")
                found.append((path, info[0], info[1], score, ", ".join(why)))
    found.sort(key=lambda x: -x[3])
    seen, result = set(), []
    for item in found:
        k = _key(item[0])
        if k not in seen:
            seen.add(k)
            result.append(item)
    return result[:limit]


# ================= дубликаты =================
QUICK_CHUNK = 64 * 1024
FULL_CHUNK = 1024 * 1024


def quick_hash(path, size):
    """Отпечаток по размеру, началу и концу файла - быстро отсеивает разные файлы."""
    h = hashlib.blake2b(digest_size=16)
    h.update(str(size).encode())
    with open(path, "rb") as fh:
        h.update(fh.read(QUICK_CHUNK))
        if size > QUICK_CHUNK:
            fh.seek(max(size - QUICK_CHUNK, QUICK_CHUNK))
            h.update(fh.read(QUICK_CHUNK))
    return h.hexdigest()


def full_hash(path):
    h = hashlib.blake2b(digest_size=20)
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(FULL_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def find_duplicate_hashes(candidates):
    """Для фонового потока. candidates: [(id, путь, размер, qhash, fhash)] - из db.dup_candidates().

    Три сита, как у хороших поисковиков дублей: размер -> начало+конец -> всё содержимое.
    Полностью читаются только файлы, совпавшие по первым двум. Посчитанное хранится
    в базе и не пересчитывается, пока файл не изменился.
    -> {id: (qhash, fhash или None)} - только то, что надо записать.
    """
    updates = {}
    by_size = {}
    for fid, path, size, q, fh in candidates:
        by_size.setdefault(size, []).append([fid, path, size, q, fh])
    for group in by_size.values():
        if len(group) < 2:
            continue
        for item in group:
            if item[3] is None:
                try:
                    item[3] = quick_hash(item[1], item[2])
                    updates[item[0]] = (item[3], None)
                except OSError:
                    item[3] = "unreadable:" + str(item[0])
        by_quick = {}
        for item in group:
            by_quick.setdefault(item[3], []).append(item)
        for same in by_quick.values():
            if len(same) < 2:
                continue
            for item in same:
                if item[4] is None:
                    try:
                        item[4] = full_hash(item[1])
                        updates[item[0]] = (item[3], item[4])
                    except OSError:
                        continue
    return updates
