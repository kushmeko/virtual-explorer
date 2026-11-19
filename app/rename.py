"""Пакетное переименование файлов - с предпросмотром, проверками и отменой (Ctrl+Z).

Шаблон имени (расширение остаётся прежним):
    {имя}    старое имя без расширения
    {n}      счётчик (с какого числа и сколько цифр - задаётся отдельно)
    {дата}   дата изменения файла, 2026-11-08
    {папка}  имя папки, где лежит файл
    {тег}    первый твой тег файла (или пусто)
Плюс «найти → заменить» и регистр. Например: «Отпуск {n}» -> Отпуск 01.jpg, Отпуск 02.jpg …
"""
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime

BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
CASES = ("как есть", "строчные", "ПРОПИСНЫЕ", "Первая заглавная")


@dataclass
class Options:
    pattern: str = "{имя}"
    start: int = 1
    digits: int = 2
    find: str = ""
    replace: str = ""
    case: str = "как есть"


@dataclass
class Item:
    file_id: int
    old_path: str
    new_path: str
    error: str = ""

    @property
    def changed(self):
        return self.old_path != self.new_path


def _apply_case(text, case):
    if case == "строчные":
        return text.lower()
    if case == "ПРОПИСНЫЕ":
        return text.upper()
    if case == "Первая заглавная":
        return text[:1].upper() + text[1:].lower()
    return text


def make_plan(files, opts, first_tags=None):
    """files: строки базы (id, path, name, mtime) в нужном порядке. -> [Item]."""
    first_tags = first_tags or {}
    plan = []
    for i, f in enumerate(files):
        stem, ext = os.path.splitext(f["name"])
        when = datetime.fromtimestamp(f["mtime"] or 0).strftime("%Y-%m-%d")
        name = (opts.pattern
                .replace("{имя}", stem)
                .replace("{n}", str(opts.start + i).zfill(max(1, opts.digits)))
                .replace("{дата}", when)
                .replace("{папка}", os.path.basename(os.path.dirname(f["path"])))
                .replace("{тег}", first_tags.get(f["id"], "")))
        if opts.find:
            name = name.replace(opts.find, opts.replace)
        name = _apply_case(name, opts.case).strip().rstrip(".")
        new_path = os.path.join(os.path.dirname(f["path"]), name + ext)
        item = Item(f["id"], f["path"], new_path)
        if not name:
            item.error = "пустое имя"
        elif BAD_CHARS.search(name):
            item.error = 'нельзя символы \\ / : * ? " < > |'
        elif name.lower() in RESERVED:
            item.error = "имя зарезервировано Windows"
        elif len(new_path) > 259:
            item.error = "слишком длинный путь"
        plan.append(item)

    # конфликты: два файла получают одно имя, или имя занято файлом не из списка
    olds = {os.path.normcase(it.old_path) for it in plan}
    seen = {}
    for it in plan:
        if it.error or not it.changed:
            continue
        key = os.path.normcase(it.new_path)
        if key in seen:
            it.error = "такое имя уже получает другой файл"
            seen[key].error = seen[key].error or "такое имя уже получает другой файл"
        else:
            seen[key] = it
        if key not in olds and os.path.exists(it.new_path):
            it.error = "файл с таким именем уже есть"
    return plan


def apply_plan(plan):
    """Переименовывает файлы на диске. Сначала во временные имена - так можно менять
    местами (a->b, b->a). Возвращает [(file_id, old, new)] сделанного.
    Если что-то пошло не так - откатывает уже сделанное и бросает OSError."""
    todo = [it for it in plan if it.changed and not it.error]
    temps, done = [], []
    try:
        for it in todo:
            tmp = os.path.join(os.path.dirname(it.old_path), f".ve_rename_{uuid.uuid4().hex[:8]}")
            os.rename(it.old_path, tmp)
            temps.append((it, tmp))
        for it, tmp in temps:
            os.rename(tmp, it.new_path)
            done.append((it, tmp))
    except OSError:
        for it, tmp in reversed(done):        # откат: new -> tmp
            try:
                os.rename(it.new_path, tmp)
            except OSError:
                pass
        for it, tmp in reversed(temps):       # tmp -> old
            try:
                os.rename(tmp, it.old_path)
            except OSError:
                pass
        raise
    return [(it.file_id, it.old_path, it.new_path) for it in todo]


def revert(done):
    """Отмена переименования: возвращает старые имена (тоже через временные)."""
    plan = [Item(fid, new, old) for fid, old, new in done]
    return apply_plan(plan)
