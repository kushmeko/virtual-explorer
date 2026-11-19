"""Журнал ошибок: errors.log в папке данных программы.

У установленной программы нет консоли, поэтому без журнала ошибка просто «исчезает».
Сюда пишутся:
  * необработанные ошибки Python (с полным текстом) - и программа показывает окно с ошибкой,
    а не закрывается молча;
  * аварийные падения самой Qt (как вылет сетки в v1.3) - через faulthandler.
Журнал не растёт бесконечно: больше 1 МБ - старая половина обрезается.
"""
import datetime
import faulthandler
import sys
import traceback

from app import paths
from app.version import VERSION

LOG_NAME = "errors.log"
MAX_BYTES = 1_000_000
_state = {"file": None, "shown": False}


def log_path():
    return paths.data_dir() / LOG_NAME


def _trim(path):
    try:
        if path.exists() and path.stat().st_size > MAX_BYTES:
            data = path.read_bytes()[-MAX_BYTES // 2:]
            path.write_bytes(b"...\n" + data)
    except OSError:
        pass


def write(text):
    path = log_path()
    _trim(path)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n=== {stamp}  v{VERSION} ===\n{text.rstrip()}\n")
    except OSError:
        pass


def _show(text):
    """Окно с ошибкой (один раз за запуск, чтобы не завалить окнами)."""
    if _state["shown"] or "--self-test" in sys.argv:   # самопроверка не должна ждать нажатия
        return
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: PLC0415
        if QApplication.instance() is None:
            return
        _state["shown"] = True
        box = QMessageBox()
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle("Виртуальный проводник - ошибка")
        box.setText("Что-то пошло не так. Программа продолжит работу, но лучше её перезапустить.")
        box.setInformativeText(f"Подробности записаны в файл:\n{log_path()}\n\n"
                               "Пришли этот файл разработчику - так ошибку быстрее исправят.")
        box.setDetailedText(text[-4000:])
        box.exec()
    except Exception:  # noqa: BLE001 - окно с ошибкой не должно ронять программу
        pass


def _excepthook(exc_type, exc, tb):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    write(text)
    if sys.stderr:
        sys.stderr.write(text)
    _show(text)


def install():
    """Включить журнал. Звать в самом начале main()."""
    sys.excepthook = _excepthook
    path = log_path()
    _trim(path)
    try:
        # файл держим открытым весь запуск: faulthandler пишет в него при падении Qt
        _state["file"] = open(path, "a", encoding="utf-8")  # noqa: SIM115
        faulthandler.enable(_state["file"], all_threads=True)
    except (OSError, RuntimeError, ValueError):
        pass
