"""Слежение за папками библиотеки в фоне.

  * QFileSystemWatcher сообщает "в папке что-то изменилось" (файл появился/пропал/переименован)
  * ждём DEBOUNCE_MS тишины (копирование 100 файлов = 100 событий -> одна проверка)
  * проверяем только изменившиеся папки: диск - в фоновом потоке, база - в главном
  * полная проверка: при запуске, раз в FULL_CHECK_MIN минут и по кнопке
    (ловит то, что слежение пропустило: изменения, пока программа была закрыта,
    файлы вне папок библиотеки, вставленную обратно флешку)
"""
from PySide6.QtCore import QFileSystemWatcher, QObject, QRunnable, QThreadPool, QTimer, Signal

import os

from app import sync

DEBOUNCE_MS = 1500
FULL_CHECK_MIN = 5
MAX_WATCHED_DIRS = 4000   # больше Windows держать не любит; остальное поймает полная проверка


class _Signals(QObject):
    done = Signal(object)


class _CollectJob(QRunnable):
    def __init__(self, known, roots, dirs, signals):
        super().__init__()
        self.args = (known, roots, dirs)
        self.signals = signals

    def run(self):
        try:
            snap = sync.collect(*self.args)
        except Exception:  # диск отвалился посреди проверки и т.п. - не роняем программу
            snap = None
        self.signals.done.emit(snap)


class LibraryWatcher(QObject):
    """checked(Report, manual) - проверка закончилась."""

    checked = Signal(object, bool)

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.fsw = QFileSystemWatcher(self)
        self.fsw.directoryChanged.connect(self._on_dir_changed)

        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(DEBOUNCE_MS)
        self.debounce.timeout.connect(self._flush)

        self.periodic = QTimer(self)
        self.periodic.setInterval(FULL_CHECK_MIN * 60 * 1000)
        self.periodic.timeout.connect(lambda: self.check_all(manual=False))
        self.periodic.start()

        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self._signals = _Signals()
        self._signals.done.connect(self._on_collected)

        self.running = False
        self.enabled = True          # в безопасном режиме слежение выключено до первой ручной проверки
        self.known_count_hint = []
        self.pending_dirs = set()
        self.pending_full = False
        self.pending_manual = False
        self._current_manual = False

    # ---------- запросы проверки ----------
    def check_all(self, manual=True):
        if not self.enabled and not manual:
            return
        self.enabled = True
        self.pending_full = True
        self.pending_manual = self.pending_manual or manual
        self._flush()

    def _on_dir_changed(self, path):
        if not self.enabled:
            return
        self.pending_dirs.add(path)
        self.debounce.start()

    def _flush(self):
        if self.running:
            return  # запустим сразу после текущей
        if self.pending_full:
            dirs, manual = None, self.pending_manual
            self.pending_full = self.pending_manual = False
            self.pending_dirs.clear()
        elif self.pending_dirs:
            dirs, manual = sorted(self.pending_dirs), False
            self.pending_dirs.clear()
        else:
            return
        self.running = True
        self._current_manual = manual
        known = self.db.all_paths()
        self.known_count_hint = known
        self.pool.start(_CollectJob(known, self.db.get_folders(), dirs, self._signals))

    def _on_collected(self, snap):
        self.running = False
        if snap is not None:
            report = sync.apply(self.db, snap)
            self._watch(snap.dirs, snap.full)
            self.checked.emit(report, self._current_manual)
        if self.pending_full or self.pending_dirs:
            QTimer.singleShot(0, self._flush)

    # ---------- какие папки слушать ----------
    def _watch(self, dirs, full):
        """Обновляет список слушаемых папок по разнице - без снятия и повторной подписки на все."""
        roots = self.db.get_folders()
        wanted = list(dict.fromkeys(roots + list(dirs)))[:MAX_WATCHED_DIRS]
        have = set(self.fsw.directories())
        if full:
            gone = [d for d in have if d not in set(wanted)]
            if gone:
                self.fsw.removePaths(gone)
                have -= set(gone)
        new = [d for d in wanted if d not in have][:max(0, MAX_WATCHED_DIRS - len(have))]
        if new:
            self.fsw.addPaths(new)
        # большие библиотеки проверяем полностью реже - меньше нагрузка на диск
        n = len(self.known_count_hint)
        minutes = FULL_CHECK_MIN if n < 20_000 else (15 if n < 100_000 else 30)
        self.periodic.setInterval(minutes * 60 * 1000)

    def shutdown(self):
        self.periodic.stop()
        self.debounce.stop()
        self.pool.clear()
        self.pool.waitForDone(3000)


# ================= любая долгая работа с диском в фоне =================
class _FuncJob(QRunnable):
    def __init__(self, func, args, signals):
        super().__init__()
        self.func, self.args, self.signals = func, args, signals

    def run(self):
        try:
            result = self.func(*self.args)
        except Exception as exc:  # noqa: BLE001 - результатом станет ошибка, окно не падает
            result = exc
        self.signals.done.emit(result)


class Background(QObject):
    """run(функция, аргументы, колбэк) - функция в фоне, колбэк в главном потоке."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self._jobs = []

    def run(self, func, args, callback):
        signals = _Signals()
        self._jobs.append(signals)  # держим ссылку, пока работа не закончилась

        def finish(result, s=signals):
            self._jobs.remove(s)
            callback(result)

        signals.done.connect(finish)
        self.pool.start(_FuncJob(func, args, signals))

    def shutdown(self):
        self.pool.clear()
        self.pool.waitForDone(3000)



# ================= добавление папки в фоне =================
class _AdderSignals(QObject):
    batch = Signal(list)          # [(путь, stat_info)] - записать в базу
    progress = Signal(int, str)   # сколько файлов найдено, текущая папка
    ask_big = Signal(int)         # набралось много файлов - спросить, продолжать ли
    finished = Signal(bool, int)  # отменено?, сколько найдено


class _AddJob(QRunnable):
    BATCH = 1500

    def __init__(self, folder, signals, adder):
        super().__init__()
        self.folder, self.signals, self.adder = folder, signals, adder

    def run(self):
        from app.db import stat_info
        from app.safety import BIG_FOLDER_FILES, walk_files
        found, batch, last_dir = 0, [], ""
        asked = False
        try:
            for path, _entry in walk_files(self.folder, cancelled=self.adder.is_cancelled):
                info = stat_info(path)
                if info is None:
                    continue
                batch.append((path, info))
                found += 1
                d = os.path.dirname(path)
                if len(batch) >= self.BATCH:
                    self.signals.batch.emit(batch)
                    batch = []
                if d != last_dir and found % 200 == 0:
                    last_dir = d
                    self.signals.progress.emit(found, d)
                if found >= BIG_FOLDER_FILES and not asked:
                    asked = True
                    self.signals.progress.emit(found, d)
                    self.signals.ask_big.emit(found)
                    self.adder.decision.wait()        # ждём ответа пользователя
                    if self.adder.is_cancelled():
                        break
            if batch and not self.adder.is_cancelled():
                self.signals.batch.emit(batch)
        finally:
            self.signals.finished.emit(self.adder.is_cancelled(), found)


class FolderAdder(QObject):
    """Обходит папку в фоновом потоке (окно не зависает) и отдаёт файлы пачками.
    Отмена - cancel(). На BIG_FOLDER_FILES файлах спрашивает, продолжать ли (answer_big)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        import threading
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.signals = _AdderSignals()
        self._cancel = threading.Event()
        self.decision = threading.Event()
        self.busy = False

    def start(self, folder):
        self._cancel.clear()
        self.decision.clear()
        self.busy = True
        self.pool.start(_AddJob(folder, self.signals, self))

    def is_cancelled(self):
        return self._cancel.is_set()

    def cancel(self):
        self._cancel.set()
        self.decision.set()

    def answer_big(self, go_on):
        if not go_on:
            self._cancel.set()
        self.decision.set()

    def shutdown(self):
        self.cancel()
        self.pool.waitForDone(3000)
