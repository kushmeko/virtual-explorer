"""Где программа хранит СВОИ данные.

В отличие от TagSpaces (.ts-папки), TagStudio (.TagStudio в корне библиотеки) и
Tagging for Windows (скрытые папки на каждом диске), мы НИЧЕГО не кладём рядом
с файлами пользователя. Всё - в одной папке программы:

    Windows:  %LOCALAPPDATA%\\VirtualExplorer\\
    другие:   ~/.local/share/VirtualExplorer/
        virtual_explorer.db     база (теги, коллекции, ...)
        thumbs_cache/           кэш обложек
        backups/                автоматические резервные копии базы

Переменная окружения VE_DATA_DIR позволяет указать другую папку (портативный режим, тесты).
"""
import os
import shutil
from pathlib import Path

APP_DIR_NAME = "VirtualExplorer"
DB_NAME = "virtual_explorer.db"


def data_dir():
    custom = os.environ.get("VE_DATA_DIR")
    if custom:
        base = Path(custom)
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_DIR_NAME
    else:
        base = Path.home() / ".local" / "share" / APP_DIR_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def db_path():
    return data_dir() / DB_NAME


def thumbs_dir():
    return data_dir() / "thumbs_cache"


def backups_dir():
    d = data_dir() / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def migrate_old_db(old_dir=None):
    """До v0.7 база лежала в папке запуска. Копируем её в папку программы (один раз).
    Старый файл не удаляем - пусть останется как ещё одна копия."""
    old = Path(old_dir or os.getcwd()) / DB_NAME
    new = db_path()
    if old.exists() and not new.exists() and old.resolve() != new.resolve():
        shutil.copy2(old, new)
        return old
    return None
