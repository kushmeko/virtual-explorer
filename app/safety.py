"""Защита от «добавил весь диск C - всё зависло».

1. check_folder() - перед добавлением папки:
     block - нельзя: весь системный диск, Windows, Program Files, ProgramData, AppData,
             папка самой программы. Там сотни тысяч служебных файлов, которые тегами не размечают.
     warn  - можно, но спросим: корень другого диска, вся папка пользователя.
     ok    - обычная папка.
2. skip_dir() - при обходе папок пропускаем служебные и системные папки
   (в том числе скрытые/системные по атрибутам Windows), а также папки разработки
   вроде node_modules и .git, где десятки тысяч мелких файлов.
3. BIG_FOLDER_FILES - после стольких файлов добавление встанет на паузу и спросит, продолжать ли.
"""
import os
import stat
import sys

BIG_FOLDER_FILES = 50_000

# имена папок, которые всегда пропускаем при обходе (регистр не важен)
SKIP_DIR_NAMES = {
    "windows", "program files", "program files (x86)", "programdata", "appdata",
    "$recycle.bin", "system volume information", "recovery", "perflogs", "$windows.~bt",
    "$windows.~ws", "$winreagent", "config.msi", "msocache", "intel", "amd", "nvidia",
    "node_modules", ".git", ".svn", ".hg", "__pycache__", ".venv", "venv", "site-packages",
    ".gradle", ".idea", ".vs", ".cache", "thumbs_cache", "onedrivetemp",
}

_HIDDEN_OR_SYSTEM = getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 2) | getattr(stat, "FILE_ATTRIBUTE_SYSTEM", 4)
# «ссылки-папки» Windows (junction, symlink): по ним не ходим - иначе можно уйти по кругу
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def _norm(path):
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def _env_dirs(*names):
    out = []
    for n in names:
        v = os.environ.get(n)
        if v:
            out.append(_norm(v))
    return out


def system_drive_root():
    if sys.platform == "win32":
        return _norm(os.environ.get("SystemDrive", "C:") + "\\")
    return "/"


def is_drive_root(path):
    p = os.path.abspath(path)
    drive, rest = os.path.splitdrive(p)
    return rest in ("\\", "/", "") or p == os.path.dirname(p)


def check_folder(path, data_dir=None):
    """-> (уровень, сообщение). уровень: "ok" | "warn" | "block"."""
    p = _norm(path)
    if not os.path.isdir(p):
        return "block", "Такой папки нет."
    if data_dir and (p == _norm(data_dir) or p.startswith(_norm(data_dir) + os.sep)):
        return "block", "Это папка с данными самой программы."

    if is_drive_root(p) and p == system_drive_root():
        return "block", ("Это весь системный диск. На нём сотни тысяч служебных файлов Windows и программ - "
                         "библиотека станет огромной, а программа будет долго всё проверять.\n\n"
                         "Добавь папки, где лежат твои файлы: Документы, Загрузки, Рабочий стол, Картинки…")
    system = _env_dirs("SystemRoot", "WINDIR", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432",
                       "ProgramData", "APPDATA", "LOCALAPPDATA")
    if sys.platform != "win32":
        system += [_norm(x) for x in ("/usr", "/bin", "/etc", "/proc", "/sys", "/dev", "/var", "/lib")]
    for s in system:
        if p == s or p.startswith(s + os.sep):
            return "block", ("Это системная папка (Windows, программы или их служебные данные). "
                             "Там нечего размечать тегами, а файлов очень много.")
    if os.path.basename(p) in SKIP_DIR_NAMES:
        return "block", "Это служебная папка - её содержимое программа всё равно пропускает."

    if is_drive_root(p):
        return "warn", ("Это весь диск целиком. Системные и служебные папки будут пропущены, но файлов "
                        "может быть очень много - добавление займёт время.\n\nПродолжить?")
    home = _norm(os.path.expanduser("~"))
    if p == home or p == os.path.dirname(home):
        return "warn", ("Это вся папка пользователя. AppData и другие служебные папки будут пропущены, "
                        "но файлов может быть очень много.\n\nЛучше добавить отдельные папки: "
                        "Документы, Загрузки, Рабочий стол, Картинки. Всё равно продолжить?")
    return "ok", ""


def skip_dir(entry_or_path, name=None):
    """Пропускать ли папку при обходе. Принимает os.DirEntry или путь."""
    if name is None:
        name = entry_or_path.name if hasattr(entry_or_path, "name") else os.path.basename(entry_or_path)
    low = name.lower()
    if low in SKIP_DIR_NAMES or low.startswith("$"):
        return True
    if hasattr(entry_or_path, "is_junction"):
        try:
            if entry_or_path.is_junction() or entry_or_path.is_symlink():
                return True
        except OSError:
            return True
    if sys.platform == "win32":
        try:
            st = entry_or_path.stat(follow_symlinks=False) if hasattr(entry_or_path, "stat") \
                else os.stat(entry_or_path, follow_symlinks=False)
            attrs = getattr(st, "st_file_attributes", 0)
            if attrs & (_HIDDEN_OR_SYSTEM | _REPARSE_POINT):
                return True
        except OSError:
            return True
    return False


def walk_files(top, cancelled=lambda: False):
    """Как os.walk, но пропускает служебные папки, не идёт по ссылкам и умеет остановиться.
    Выдаёт (путь, os.DirEntry) для каждого файла."""
    stack = [top]
    while stack:
        if cancelled():
            return
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                entries = list(it)
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_dir(follow_symlinks=False):
                    if not skip_dir(e):
                        stack.append(e.path)
                elif e.is_file(follow_symlinks=False):
                    yield e.path, e
            except OSError:
                continue
