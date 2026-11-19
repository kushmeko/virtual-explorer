import os
import sys

# --self-test <файл>: быстрая проверка собранной программы (её запускает сборка на GitHub).
# Работает во временной папке и не трогает настоящие данные - поэтому до всех импортов.
SELF_TEST = "--self-test" in sys.argv
if SELF_TEST:
    import tempfile
    os.environ["VE_DATA_DIR"] = tempfile.mkdtemp(prefix="ve_selftest_")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from app import backup, crashlog, paths  # noqa: E402
from app.db import Database  # noqa: E402
from app.settings import Settings  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.theme import apply_theme  # noqa: E402
from app.version import APP_NAME, VERSION  # noqa: E402

# Метка «программа сейчас запущена». Если при запуске она уже есть - прошлый раз программа
# не закрылась нормально (зависла, её сняли через диспетчер задач). Тогда предлагаем
# безопасный режим: без проверки файлов, чтобы можно было убрать проблемную папку.
# Раньше в такой ситуации приходилось вручную чистить папку программы в AppData.
LOCK_NAME = "running.lock"
ICON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app", "assets", "icon.png")


def ask_safe_mode(app):
    box = QMessageBox()
    box.setWindowTitle(APP_NAME)
    box.setIcon(QMessageBox.Warning)
    box.setText("Прошлый запуск завершился не до конца - возможно, программа зависла.")
    box.setInformativeText(
        "Запустить в безопасном режиме? Программа не будет проверять файлы на диске и откроет "
        "«Папки библиотеки» - там можно убрать слишком большую папку.\n\n"
        "Теги, коллекции и настройки никуда не денутся.")
    safe = box.addButton("Безопасный режим", QMessageBox.AcceptRole)
    box.addButton("Обычный запуск", QMessageBox.RejectRole)
    box.setDefaultButton(safe)
    box.exec()
    return box.clickedButton() is safe


def bring_to_front(window):
    if window.isMinimized():
        window.showNormal()
    window.show()
    window.raise_()
    window.activateWindow()


def self_test_report(window):
    """Проверки собранной программы. -> список (что, ок, подробности)."""
    from app.ui import theme, thumbs  # noqa: PLC0415
    checks = [("Главное окно", window.isVisible(), "")]
    checks.append(("Шрифт Inter", bool(theme.bundled_font()), str(theme.FONTS_DIR)))
    checks.append(("Значок", os.path.exists(ICON), ICON))
    checks.append(("Обложки PDF (QtPdf)", thumbs.PDF_COVERS, ""))
    try:
        from PySide6 import QtMultimedia  # noqa: F401, PLC0415
        checks.append(("Видео и звук (QtMultimedia)", True, ""))
    except ImportError as e:
        checks.append(("Видео и звук (QtMultimedia)", False, str(e)))
    folder = paths.data_dir() / "test_files"
    folder.mkdir(exist_ok=True)
    (folder / "заметка.txt").write_text("проверка", encoding="utf-8")
    window.db.add_file(str(folder / "заметка.txt"))
    checks.append(("База: добавление файла", window.db.count_files() >= 1, ""))
    return checks


def run_self_test(app, window, out_path):
    def finish():
        code = 0
        lines = [f"{APP_NAME} {VERSION} - самопроверка"]
        try:
            for name, ok, info in self_test_report(window):
                lines.append(f"[{'OK' if ok else 'FAIL'}] {name} {info}".rstrip())
                code |= 0 if ok else 1
        except Exception as e:  # noqa: BLE001
            lines.append(f"[FAIL] исключение: {e!r}")
            code = 1
        lines.append("SELFTEST " + ("OK" if code == 0 else "FAILED"))
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        window.close()
        app.exit(code)
    QTimer.singleShot(2500, finish)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("VirtualExplorer")
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(VERSION)
    if os.path.exists(ICON):
        app.setWindowIcon(QIcon(ICON))
    crashlog.install()

    single = None
    if not SELF_TEST:
        from app.single import SingleInstance  # noqa: PLC0415
        single = SingleInstance(app)
        if single.already_running():   # программа уже открыта - просто показали её окно
            sys.exit(0)

    # до v0.7 база лежала рядом с программой - один раз копируем её в папку данных
    paths.migrate_old_db()
    lock = paths.data_dir() / LOCK_NAME
    safe_mode = "--safe" in sys.argv
    db = Database()
    st = Settings(db)
    if SELF_TEST:
        st.set("onboarding_done", True)
    apply_theme(app, st)
    if lock.exists() and not safe_mode and not SELF_TEST:
        safe_mode = ask_safe_mode(app)
    lock.write_text("1", encoding="utf-8")
    code = 1
    try:
        backup.auto_backup_if_due(db.conn)  # копия базы раз в сутки
        window = MainWindow(db, safe_mode=safe_mode)
        window.show()
        if single is not None:
            single.activate.connect(lambda: bring_to_front(window))
        if SELF_TEST:
            i = sys.argv.index("--self-test")
            out = sys.argv[i + 1] if i + 1 < len(sys.argv) else "selftest.txt"
            run_self_test(app, window, out)
        code = app.exec()
    finally:
        try:
            lock.unlink()
        except OSError:
            pass
    sys.exit(code)


if __name__ == "__main__":
    main()
