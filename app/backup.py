"""Резервные копии базы.

Tabbles: «я терял большие базы тегов», «нет резервного копирования»;
Tagging for Windows: «копируйте базы вручную». Здесь копии делаются сами:
  * раз в сутки при запуске
  * перед опасными действиями (слияние тегов, «убрать все потерянные», импорт, восстановление)
Хранится последних KEEP копий. Восстановление - из окна «Резервные копии».
"""
import sqlite3
from datetime import datetime, timedelta

from app.paths import backups_dir

KEEP = 15
PREFIX = "virtual_explorer_"


def make_backup(conn, reason="auto"):
    """Копия базы средствами SQLite (безопасно даже во время работы). Возвращает путь."""
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    safe_reason = "".join(ch for ch in reason if ch.isalnum() or ch in "-_")[:30] or "auto"
    path = backups_dir() / f"{PREFIX}{stamp}_{safe_reason}.db"
    n = 1
    while path.exists():
        path = backups_dir() / f"{PREFIX}{stamp}_{safe_reason}_{n}.db"
        n += 1
    target = sqlite3.connect(path)
    try:
        conn.commit()
        conn.backup(target)
    finally:
        target.close()
    prune()
    return path


def list_backups():
    """[(путь, время, причина, размер)] - новые первыми."""
    result = []
    for p in backups_dir().glob(PREFIX + "*.db"):
        parts = p.stem[len(PREFIX):].split("_")
        try:
            when = datetime.strptime(parts[0] + "_" + parts[1], "%Y-%m-%d_%H-%M-%S")
        except (ValueError, IndexError):
            when = datetime.fromtimestamp(p.stat().st_mtime)
        reason = "_".join(parts[2:]) or "auto"
        result.append((p, when, reason, p.stat().st_size))
    result.sort(key=lambda r: r[1], reverse=True)
    return result


def prune(keep=KEEP):
    for p, *_ in list_backups()[keep:]:
        try:
            p.unlink()
        except OSError:
            pass


def auto_backup_if_due(conn, hours=24):
    items = [b for b in list_backups() if b[2] == "auto"]
    if items and datetime.now() - items[0][1] < timedelta(hours=hours):
        return None
    return make_backup(conn, "auto")


def restore(conn, path):
    """Заменяет содержимое открытой базы копией (на месте). Перед этим - копия текущего."""
    make_backup(conn, "before-restore")
    src = sqlite3.connect(path)
    try:
        src.backup(conn)
    finally:
        src.close()


REASONS = {
    "auto": "ежедневная",
    "before-restore": "перед восстановлением",
    "merge-tags": "перед слиянием тегов",
    "remove-missing": "перед удалением потерянных",
    "remove-folder": "перед удалением папки",
    "import": "перед импортом",
    "manual": "вручную",
    "delete-tag": "перед удалением тега",
    "remove-dups": "перед удалением дубликатов",
}
