"""Главное окно.

   ┌ сайдбар ─────┬ центр ───────────────────────────┬ детали файла ──┐
   │ Библиотека   │ поиск, сортировка                │ превью, имя, ★ │
   │ (+⚠ потерян.)│ И/ИЛИ, найти тег, менеджер тегов │ теги (✕ снять) │
   │ Коллекции    │ плашки-теги по группам (✓ / ✕)   │ 🏷 Метки…      │
   │ Динамические │ сетка / таблица (мультивыбор)    │ коллекции      │
   └──────────────┴──────────────────────────────────┴────────────────┘

Файлы на диске проверяет LibraryWatcher (app/ui/watch.py + app/sync.py):
переехавшие находятся вместе с тегами, пропавшие помечаются "⚠ Потерянные".

Файлы можно тащить мышкой из сетки/таблицы на коллекцию, ★ Избранное
или заголовок "КОЛЛЕКЦИИ" (= новая коллекция) - см. app/ui/dnd.py.

v1.0: Ctrl+Z отменяет любое действие (UNDOABLE ниже), F1 - горячие клавиши,
Пробел - быстрый просмотр, значки тегов на обложках (app/ui/icons.py).

Фильтр по тегам как в магазине Steam:
   клик по плашке:  не важно → ✓ нужен → ✕ исключить → не важно
   счётчик на плашке = сколько файлов с этим тегом среди найденных сейчас
"""
import os
import subprocess
import time
from collections import OrderedDict
from datetime import datetime, timezone

from PySide6.QtCore import QByteArray, QItemSelectionModel, QSize, QStringListModel, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QBrush, QColor, QDesktopServices, QIcon, QImageReader, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCompleter,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QApplication,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QTableWidgetItem,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import backup, paths, query, transfer
from app.db import AUTO_GROUP, FileFilter
from app.settings import Settings
from app import colors as color_names
from app import crashlog, rename, safety, trash, undo, updates
from app.sync import find_candidates, find_duplicate_hashes
from app.ui.icons import badge_icon, badges_key, order_badges
from app.ui.theme import apply_theme
from app.version import APP_NAME, GITHUB_REPO, VERSION, short_version
from app.ui.settings_dialog import SettingsDialog
from app.ui.guide import GuideDialog
from app.ui.tour import Tour
from app.ui.quickview import QuickView
from app.ui.dialogs import (
    AutoRulesDialog,
    choose_parent,
    BackupsDialog,
    CandidatesDialog,
    DynamicCollectionDialog,
    FoldersToTagsDialog,
    LibraryFoldersDialog,
    RenameDialog,
    StatsDialog,
    TagEditorDialog,
    TagIconDialog,
    TagManagerDialog,
)
from app.ui.watch import Background, FolderAdder, LibraryWatcher
from app.ui.dnd import FileGrid, FileTable, SidebarTree
from app.ui.thumbs import COVER_H, COVER_W, IMAGE_EXTS, PREVIEW_EXTS, ThumbnailLoader, compose_cover, compute_colors, placeholder_image
from app.ui.widgets import (
    FlowLayout,
    StarRating,
    TagChip,
    clear_layout,
    make_filter_chip,
    make_group_label,
)

COL_FAV, COL_NAME, COL_TAGS, COL_SIZE, COL_PATH, COL_RATING = range(6)  # оценка показывается 3-й
# фильтры раздела «Все файлы / Избранное / Недавние» (ПКМ) - раньше это были отдельные разделы
SUB_FILTERS = {
    "no_tags": "Без тегов",
    "no_user_tags": "Без своих тегов",
    "no_auto_tags": "Без авто-тегов",
}
SUB_FILTER_HINTS = {
    "no_tags": "ни одного тега - даже авто-тега по типу (неизвестные файлы)",
    "no_user_tags": "нет твоих тегов (авто-теги вроде «Картинки» не считаются)",
    "no_auto_tags": "тип файла не распознан, свои теги могут быть",
}
SUB_FILTER_EMPTY = {
    "no_tags": ("Все файлы разобраны", "Здесь появятся файлы, к которым не подобрался ни один тег."),
    "no_user_tags": ("Все файлы с тегами", "У каждого файла есть хотя бы один твой тег. Отлично!"),
    "no_auto_tags": ("Все типы файлов знакомы", "Нет файлов неизвестного типа."),
}
PAGE = 1000
# пределы памяти для сетки обложек (v1.4: без них 2000+ картинок роняли программу)
COVER_CACHE_LIMIT = 500     # готовых обложек в кэше
COVER_IMAGES_LIMIT = 400    # загруженных превью (остальные быстро читаются из кэша на диске)
REAL_ICONS_LIMIT = 500      # плиток с настоящей обложкой; дальние снова получают заглушку       # сколько файлов показывать за раз (дальше - «Показать ещё»)
CHIP_LIMIT = 20   # сколько плашек показывать, пока не нажали "Ещё…"
NO_GROUP = "Метки"


def fmt_date(sqlite_utc):
    """'2026-10-31 19:10:00' (UTC из SQLite) -> '31.10 22:10' по местному времени."""
    try:
        dt = datetime.strptime(sqlite_utc, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%d.%m %H:%M")
    except (TypeError, ValueError):
        return str(sqlite_utc)


def stars_text(n):
    n = int(n or 0)
    return "★" * n + "☆" * (5 - n) if n else ""


def fmt_size(n):
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024 or unit == "ГБ":
            return f"{n:.0f} {unit}" if unit == "Б" else f"{n:.1f} {unit}"
        n /= 1024


# Действия пользователя, которые отменяются Ctrl+Z. Перед вызовом снимается копия базы;
# если действие ничего не поменяло (диалог закрыли) - копия выбрасывается.
UNDOABLE = {
    "on_tag_input": "тег", "on_remove_tag": "снять тег", "set_tag_on_selection": "быстрый тег",
    "open_tag_editor": "метки", "toggle_favorite": "избранное", "set_in_collection": "коллекция",
    "apply_drop": "перетаскивание", "on_chip_menu": "действие с тегом", "open_tag_manager": "менеджер тегов",
    "on_sidebar_menu": "коллекция", "remove_selected_from_library": "убрать из библиотеки",
    "on_missing_menu": "потерянные", "merge_copies_tags": "объединение тегов копий",
    "keep_only_this_copy": "оставить одну копию", "trash_other_copies": "копии в Корзину",
    "on_candidates": "файл найден", "new_collection": "новая коллекция",
    "new_dynamic_collection": "динамическая коллекция", "open_rules": "правила авто-тегов",
    "open_folders_to_tags": "папки → теги", "import_tags": "импорт", "open_library_folders": "папки библиотеки",
    "run_auto_tags": "авто-теги", "rate_files": "оценка", "rename_selected": "переименование",
    "open_backups": "восстановление из копии", "add_folder": "добавление папки",
    "remove_library_folder": "убрать папку",
}


class MainWindow(QMainWindow):
    def __init__(self, db, safe_mode=False):
        super().__init__()
        self.safe_mode = safe_mode
        self.settings = Settings(db)
        safety.BIG_FOLDER_FILES = int(self.settings["big_folder_files"])
        self.db = db
        self.undo = undo.UndoStack(db.conn)
        self._undo_depth = 0
        for name, label in UNDOABLE.items():   # до постройки интерфейса - чтобы сигналы шли через обёртку
            setattr(self, name, self._undoable(getattr(self, name), label))
        self.view = ("all", 0)        # что выбрано в сайдбаре: (вид, id)
        self.include = {}             # нужные теги (dict - сохраняет порядок нажатия)
        self.exclude = {}             # исключённые теги
        self.tag_mode = "all"         # "all" - все нужные (И), "any" - любой (ИЛИ)
        self.show_all_tags = False
        self.collections = []
        self._sidebar_items = {}
        self.mode = "grid"          # "grid" - обложки, "list" - таблица
        self.sort_key = "name"
        self.cover_images = OrderedDict()   # id файла -> превью (QImage), не больше COVER_IMAGES_LIMIT
        self._real_icons = set()           # у каких плиток сейчас настоящая обложка, а не заглушка
        self._placeholder_icons = {}       # (расширение, грузится, w, h) -> общая заглушка
        self.cover_meta = {}        # id файла -> (★, цвета тегов, расширение, потерян, значки, спрятано)
        self._tags_map = {}         # id тега -> строка тега (для значков на обложках)
        self.grid_items = {}        # id файла -> элемент сетки
        self.thumbs = ThumbnailLoader(self)
        self.thumbs.loaded.connect(self.on_cover_loaded)
        self.watcher = LibraryWatcher(db, self)
        self.watcher.checked.connect(self.on_files_checked)
        self.background = Background(self)
        self.adder = FolderAdder(self)
        self.adder.signals.batch.connect(self.on_add_batch)
        self.adder.signals.progress.connect(self.on_add_progress)
        self.adder.signals.ask_big.connect(self.on_add_big)
        self.adder.signals.finished.connect(self.on_add_finished)
        self._adding = None
        self.page_limit = self.page_size()
        self._filter_sig = None
        self._history, self._history_pos = [("all", 0)], 0
        # фильтр «без тегов» для «Все файлы» / «Избранное» / «Недавние» (ПКМ по ним)
        self.sub_filter = ""
        self.cover_cache = OrderedDict()   # (id, ★, цвета, …, размер) -> готовая QPixmap (LRU)
        self._covers_timer = QTimer(self)
        self._covers_timer.setSingleShot(True)
        self._covers_timer.timeout.connect(self.load_visible_covers)
        self._size_timer = QTimer(self)
        self._size_timer.setSingleShot(True)
        self._size_timer.timeout.connect(self._regrid_covers)
        self.setWindowTitle(f"{APP_NAME} v{short_version()}")
        self.net = Background(self)          # проверка обновлений - отдельно от долгих фоновых задач
        self._update_running = False
        self._dup_running = False
        self._colors_running = False
        self._note_file = None        # чья заметка сейчас в поле
        self._note_checkpointed = None
        self.resize(1300, 760)
        self._build_ui()
        self.restore_window_state()
        self.refresh_sidebar()
        self.refresh_files()
        if not self.settings["onboarding_done"]:
            QTimer.singleShot(700, self.start_tour)   # первый запуск - обучение со стрелками
        if safe_mode:
            # безопасный режим: ничего не проверяем, сразу даём убрать проблемную папку
            self.watcher.enabled = False
            QTimer.singleShot(300, self.show_safe_mode_help)
        else:
            # сначала - нет ли в библиотеке опасных папок (весь диск C и т.п.), потом проверка файлов
            QTimer.singleShot(300, self.startup_checks)

    # ================= построение интерфейса =================
    def _build_ui(self):
        toolbar = self.toolbar = self.addToolBar("Главная")
        toolbar.setMovable(False)
        # на виду - только то, что нужно каждый день; остальное в «☰ Ещё»
        self.undo_action = QAction("↶", self)
        self.undo_action.triggered.connect(self.do_undo)
        self.redo_action = QAction("↷", self)
        self.redo_action.triggered.connect(self.do_redo)
        self.back_action = QAction("◀", self)
        self.back_action.setToolTip("Назад  (Alt+←)")
        self.back_action.triggered.connect(self.go_back)
        self.fwd_action = QAction("▶", self)
        self.fwd_action.setToolTip("Вперёд  (Alt+→)")
        self.fwd_action.triggered.connect(self.go_forward)
        toolbar.addAction(self.back_action)
        toolbar.addAction(self.fwd_action)
        toolbar.addSeparator()
        toolbar.addAction(self.undo_action)
        toolbar.addAction(self.redo_action)
        toolbar.addSeparator()
        self.update_undo_actions()
        # ＋ Добавить ▾ - главная кнопка (папка, коллекция, динамическая коллекция)
        add_menu = QMenu(self)
        add_menu.addAction("📂 Папку…").triggered.connect(lambda: self.add_folder())
        add_menu.addAction("＋ Коллекцию").triggered.connect(lambda: self.new_collection())
        add_menu.addAction("⚡ Динамическую коллекцию").triggered.connect(lambda: self.new_dynamic_collection())
        add_btn = self.add_btn = QToolButton()
        add_btn.setObjectName("primary")
        add_btn.setText("＋ Добавить")
        add_btn.setToolTip("Добавить папку, коллекцию или динамическую коллекцию")
        add_btn.setMenu(add_menu)
        add_btn.setPopupMode(QToolButton.InstantPopup)
        toolbar.addWidget(add_btn)
        for text, slot, tip in [
            ("🗂 Теги", self.open_tag_manager, "Менеджер тегов: имя, цвет, значок, группа, вложенность"),
            ("🔄", lambda _=False: self.check_files(), "Проверить файлы на диске  (F5)"),
        ]:
            action = QAction(text, self)
            action.setToolTip(tip)
            action.triggered.connect(slot)
            toolbar.addAction(action)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)

        # «☰ Ещё» - по разделам
        more = QMenu(self)
        sections = [
            ("Теги", [
                ("⚙ Правила авто-тегов…", self.open_rules),
                ("📁 Папки → теги…", self.open_folders_to_tags),
                ("🏷 Авто-теги по типу файла", self.run_auto_tags),
            ]),
            ("Библиотека", [
                ("📁 Папки библиотеки…", self.open_library_folders),
                ("⧉ Найти дубликаты", lambda _=False: self.scan_duplicates(manual=True)),
                ("📊 Статистика\tCtrl+I", self.open_stats),
            ]),
            ("Данные", [
                ("💾 Резервные копии…", self.open_backups),
                ("⬆ Экспорт тегов в файл…", self.export_tags),
                ("⬇ Импорт тегов из файла…", self.import_tags),
            ]),
        ]
        for title, items in sections:
            more.addSection(title)
            for text, slot in items:
                more.addAction(text).triggered.connect(slot)
        more_btn = self.menu_btn = QToolButton()   # не more_btn: так называется «показать ещё» внизу
        more_btn.setText("☰ Ещё")
        more_btn.setMenu(more)
        more_btn.setPopupMode(QToolButton.InstantPopup)
        toolbar.addWidget(more_btn)
        settings_action = self.settings_action = QAction("⚙", self)
        settings_action.setToolTip("Настройки  (Ctrl+,)")
        settings_action.triggered.connect(lambda: self.open_settings())
        toolbar.addAction(settings_action)
        self.details_action = QAction("▤", self)
        self.details_action.setCheckable(True)
        self.details_action.setToolTip("Панель деталей файла справа")
        self.details_action.toggled.connect(self.toggle_details)
        toolbar.addAction(self.details_action)

        # --- слева: сайдбар ---
        self.sidebar = SidebarTree()
        self.sidebar.filesDropped.connect(self.on_files_dropped)
        self.sidebar.hint.connect(self.on_drop_hint)
        self.sidebar.setHeaderHidden(True)
        self.sidebar.setColumnCount(2)
        self.sidebar.header().setStretchLastSection(False)
        self.sidebar.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.sidebar.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.sidebar.setIndentation(12)
        self.sidebar.setContextMenuPolicy(Qt.CustomContextMenu)
        self.sidebar.customContextMenuRequested.connect(self.on_sidebar_menu)
        self.sidebar.currentItemChanged.connect(self.on_sidebar_changed)

        # --- центр: поиск, плашки, таблица ---
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍 Поиск: имя, тег, #тег, -#тег, .pdf, размер>10мб, добавлен:7д …")
        self.search.setClearButtonEnabled(True)
        self.search.setToolTip(query.__doc__)
        self.search.textChanged.connect(self.refresh_files)
        self.search.textChanged.connect(lambda _t: self.history_timer.start())
        self.search.textEdited.connect(self.on_search_edited)
        # автодополнение тегов: пишешь «#ко» - предлагает «#Кошки»
        self.tag_completer_model = QStringListModel(self)
        self.tag_completer = QCompleter(self.tag_completer_model, self)
        self.tag_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.tag_completer.setFilterMode(Qt.MatchStartsWith)
        self.tag_completer.setWidget(self.search)
        self.tag_completer.activated[str].connect(self.insert_completion)
        # история поиска: запоминаем запрос, если он постоял 2 секунды и что-то нашёл
        self.history_timer = QTimer(self)
        self.history_timer.setSingleShot(True)
        self.history_timer.setInterval(2000)
        self.history_timer.timeout.connect(self.remember_search)
        self.search_hint = QLabel("")
        self.search_hint.setStyleSheet("color: #74c0fc; padding-left: 4px;")
        self.search_hint.setVisible(False)
        help_btn = QToolButton()
        help_btn.setText("?")
        help_btn.setToolTip("Подсказки по поиску - нажми, чтобы вставить пример")
        help_btn.setPopupMode(QToolButton.InstantPopup)
        help_menu = QMenu(self)
        self.help_menu = help_menu
        help_menu.aboutToShow.connect(self.fill_help_menu)
        self._help_examples = [
            ("#", "#тег - файлы с тегом"),
            ("-#", "-#тег - файлы БЕЗ тега"),
            (".pdf", ".pdf - только этот тип"),
            ("размер>10мб", "размер>10мб - большие файлы"),
            ("добавлен:7д", "добавлен:7д - добавлены за неделю"),
            ("изменён:30д", "изменён:30д - менялись за месяц"),
            ("путь:", "путь:текст - где-то в пути"),
            ("★", "★ - избранное"),
            (" | ", "кот | пёс - ИЛИ"),
            ("оценка>=4", "оценка>=4 - с хорошей оценкой"),
            ("заметка:", "заметка:текст - в заметке"),
            ("дубликат", "дубликат - у файла есть копии"),
        ]
        help_btn.setMenu(help_menu)
        # поиск картинок по цвету
        color_btn = QToolButton()
        color_btn.setText("🎨")
        color_btn.setToolTip("Картинки по цвету: выбери цвет, который в них преобладает")
        color_btn.setPopupMode(QToolButton.InstantPopup)
        color_menu = QMenu(self)
        for cname, hex_color in color_names.PALETTE.items():
            sw = QPixmap(16, 16)
            sw.fill(QColor(hex_color))
            color_menu.addAction(QIcon(sw), cname).triggered.connect(
                lambda _=False, c=cname: self.insert_search(f"цвет:{c}"))
        color_btn.setMenu(color_menu)
        search_row = QHBoxLayout()
        self.sort_box = QComboBox()
        for label, key in [("По имени", "name"), ("Недавно добавленные", "added"),
                           ("По размеру", "size"), ("По типу", "ext"), ("По оценке", "rating")]:
            self.sort_box.addItem(label, key)
        self.sort_box.currentIndexChanged.connect(self.on_sort_changed)
        search_row.addWidget(self.search, 1)
        search_row.addWidget(help_btn)
        search_row.addWidget(color_btn)
        self.save_search_btn = QToolButton()
        self.save_search_btn.setText("💾")
        self.save_search_btn.setToolTip("Сохранить этот поиск (и фильтр тегов) как динамическую коллекцию")
        self.save_search_btn.clicked.connect(self.new_dynamic_collection)
        search_row.addWidget(self.save_search_btn)
        search_row.addWidget(self.sort_box)
        self.view_btn = QToolButton()
        self.view_btn.setObjectName("viewToggle")
        self.view_btn.clicked.connect(lambda: self.set_mode("list" if self.mode == "grid" else "grid"))
        search_row.addWidget(self.view_btn)
        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setRange(110, 320)
        self.size_slider.setValue(190)
        self.size_slider.setFixedWidth(110)
        self.size_slider.setToolTip("Размер обложек")
        self.size_slider.valueChanged.connect(self.apply_grid_size)
        search_row.addWidget(self.size_slider)

        # строка управления фильтром тегов
        self.mode_box = QComboBox()
        self.mode_box.addItem("Нужны все ✓ теги (И)", "all")
        self.mode_box.addItem("Нужен любой ✓ тег (ИЛИ)", "any")
        self.mode_box.setToolTip("Как сочетать отмеченные ✓ теги. Исключённые ✕ убираются всегда.")
        self.mode_box.currentIndexChanged.connect(self.on_mode_changed)
        self.chip_search = QLineEdit()
        self.chip_search.setPlaceholderText("Найти тег…")
        self.chip_search.setClearButtonEnabled(True)
        self.chip_search.setMaximumWidth(200)
        self.chip_search.textChanged.connect(self.refresh_chips)
        self.filter_summary = QLabel("")
        self.filter_summary.setStyleSheet("color: #868e96;")
        self.reset_btn = QPushButton("✕ Сбросить теги")
        self.reset_btn.clicked.connect(self.reset_tag_filter)
        self.reset_btn.setVisible(False)
        tag_row = QHBoxLayout()
        tag_row.addWidget(QLabel("Теги:"))
        tag_row.addWidget(self.mode_box)
        tag_row.addWidget(self.chip_search)
        tag_row.addWidget(self.filter_summary, 1)
        tag_row.addWidget(self.reset_btn)
        self.sub_btn = QPushButton("")
        self.sub_btn.setToolTip("Фильтр раздела (ПКМ по «Все файлы»). Нажми, чтобы снять.")
        self.sub_btn.clicked.connect(lambda: self.set_sub_filter(""))
        self.sub_btn.setVisible(False)
        tag_row.addWidget(self.sub_btn)

        self.chips_widget = QWidget()
        self.chips_widget.setToolTip("Клик: ✓ нужен → ✕ исключить → не важно.  ПКМ - меню тега")
        self.chips_layout = FlowLayout(self.chips_widget, spacing=6)

        self.table = FileTable(self.selected_file_ids, 0, 6)
        self.table.cover_provider = self.cover_pixmap
        self.table.setHorizontalHeaderLabels(["★", "Имя", "Теги", "Размер", "Путь", "Оценка"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_FAV, QHeaderView.Fixed)
        header.setStretchLastSection(True)
        self.table.setColumnWidth(COL_FAV, 32)
        self.table.setColumnWidth(COL_NAME, 260)
        self.table.setColumnWidth(COL_TAGS, 220)
        self.table.setColumnWidth(COL_SIZE, 90)
        self.table.setColumnWidth(COL_RATING, 90)
        header.moveSection(header.visualIndex(COL_RATING), 2)  # показываем сразу после имени
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.on_table_menu)
        self.table.itemSelectionChanged.connect(self.refresh_file_panel)
        self.table.cellDoubleClicked.connect(self.on_double_click)

        self.grid = FileGrid(self.selected_file_ids)
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static)
        self.grid.enable_drag()  # тащить файлы на коллекции в сайдбаре
        self.grid.setUniformItemSizes(True)
        self.grid.setWordWrap(False)
        self.grid.setTextElideMode(Qt.ElideMiddle)
        self.grid.setSpacing(6)
        self.grid.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.grid.setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self.on_grid_menu)
        self.grid.itemSelectionChanged.connect(self.refresh_file_panel)
        self.grid.itemDoubleClicked.connect(self.on_grid_double_click)
        self.grid.verticalScrollBar().valueChanged.connect(self.schedule_covers)
        self.grid.resized.connect(self.schedule_covers)

        # пустой экран: подсказывает, что делать дальше (вместо пустого серого поля)
        self.empty_page = QWidget()
        ep = QVBoxLayout(self.empty_page)
        ep.addStretch(1)
        self.empty_title = QLabel("")
        self.empty_title.setAlignment(Qt.AlignCenter)
        self.empty_title.setStyleSheet("font-size: 20px; font-weight: bold;")
        self.empty_text = QLabel("")
        self.empty_text.setAlignment(Qt.AlignCenter)
        self.empty_text.setWordWrap(True)
        self.empty_text.setStyleSheet("color: #868e96;")
        self.empty_btn = QPushButton("")
        self.empty_btn.setObjectName("primary")
        self.empty_btn.setMinimumHeight(40)
        self.empty_btn.clicked.connect(self.on_empty_action)
        self.empty_btn2 = QPushButton("🎓 Показать, где что (1 минута)")
        self.empty_btn2.setMinimumHeight(40)
        self.empty_btn2.clicked.connect(self.start_tour)
        self.empty_btn2.setVisible(False)
        ep.addWidget(self.empty_title)
        ep.addWidget(self.empty_text)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.empty_btn)
        row.addWidget(self.empty_btn2)
        row.addStretch(1)
        ep.addLayout(row)
        ep.addStretch(2)
        self.empty_action = None

        self.views = QStackedWidget()
        self.views.addWidget(self.grid)   # 0 - сетка
        self.views.addWidget(self.table)  # 1 - список
        self.views.addWidget(self.empty_page)  # 2 - пусто

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.addLayout(search_row)
        center_layout.addWidget(self.search_hint)
        center_layout.addLayout(tag_row)
        center_layout.addWidget(self.chips_widget)
        # v1.7: подсказка для новичков - пока не поставлен ни один свой тег
        self.hint_bar = QFrame()
        self.hint_bar.setObjectName("card")
        hb = QHBoxLayout(self.hint_bar)
        hb.setContentsMargins(12, 6, 6, 6)
        self.hint_label = QLabel(
            "💡 <b>Первый тег:</b> выдели файл (или несколько) и нажми <b>Ctrl+T</b> - "
            "или впиши тег в панели справа. Потом пиши <b>#тег</b> в поиске, чтобы найти файлы.")
        self.hint_label.setWordWrap(True)
        self.hint_label.setTextFormat(Qt.RichText)
        hint_close = QPushButton("Понятно ✕")
        hint_close.setToolTip("Больше не показывать эту подсказку")
        hint_close.clicked.connect(self.dismiss_tag_hint)
        hb.addWidget(self.hint_label, 1)
        hb.addWidget(hint_close)
        self.hint_bar.setVisible(False)
        center_layout.addWidget(self.hint_bar)
        # v1.8: уведомление «файл переименован или перемещён - теги сохранены»
        self.notice_bar = QFrame()
        self.notice_bar.setObjectName("card")
        nb = QHBoxLayout(self.notice_bar)
        nb.setContentsMargins(12, 6, 6, 6)
        self.notice_label = QLabel("")
        self.notice_label.setWordWrap(True)
        self.notice_label.setTextFormat(Qt.RichText)
        notice_close = QPushButton("✕")
        notice_close.setFixedWidth(32)
        notice_close.setToolTip("Скрыть")
        notice_close.clicked.connect(lambda: self.notice_bar.setVisible(False))
        nb.addWidget(self.notice_label, 1)
        nb.addWidget(notice_close)
        self.notice_bar.setVisible(False)
        self.notice_timer = QTimer(self)
        self.notice_timer.setSingleShot(True)
        self.notice_timer.timeout.connect(lambda: self.notice_bar.setVisible(False))
        center_layout.addWidget(self.notice_bar)
        center_layout.addWidget(self.views, 1)
        self.more_btn = QPushButton("")
        self.more_btn.setVisible(False)
        self.more_btn.clicked.connect(self.show_more)
        center_layout.addWidget(self.more_btn)

        # --- справа: детали выбранного файла ---
        self.file_title = QLabel("Выбери файл")
        title_font = self.file_title.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 3)
        self.file_title.setFont(title_font)
        self.file_title.setWordWrap(True)

        self.file_info = QLabel("")
        self.file_info.setWordWrap(True)
        self.file_info.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.fav_btn = QPushButton("☆ В избранное")
        self.fav_btn.setCheckable(True)
        self.fav_btn.clicked.connect(self.on_fav_clicked)

        self.file_tags_widget = QWidget()
        self.file_tags_layout = FlowLayout(self.file_tags_widget, spacing=6)

        self.tag_input = QLineEdit()
        self.tag_input.setPlaceholderText("Быстро: тег + Enter")
        self.tag_input.returnPressed.connect(self.on_tag_input)
        self.completer_model = QStringListModel(self)
        completer = QCompleter(self.completer_model, self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.tag_input.setCompleter(completer)

        self.file_collections_list = QListWidget()
        self.file_collections_list.itemChanged.connect(self.on_file_collection_toggled)

        # плашка "файла нет на диске" + что с этим делать
        self.missing_label = QLabel("")
        self.missing_label.setWordWrap(True)
        self.missing_label.setStyleSheet(
            "background: rgba(201,42,42,40); color: #ff6b6b; border: 1px solid #c92a2a;"
            " border-radius: 6px; padding: 6px;"
        )
        self.locate_btn = QPushButton("🔎 Найти, куда делся…")
        self.locate_btn.setToolTip("Поищу похожие файлы (то же имя, тот же размер, похожее имя)\n"
                                   "и предложу варианты. Теги, коллекции и ★ сохранятся.")
        self.locate_btn.clicked.connect(self.locate_selected)
        self.forget_btn = QPushButton("Убрать из библиотеки")
        self.forget_btn.clicked.connect(self.remove_selected_from_library)
        self.missing_box = QWidget()
        mb = QVBoxLayout(self.missing_box)
        mb.setContentsMargins(0, 0, 0, 0)
        mb.addWidget(self.missing_label)
        mb_row = QHBoxLayout()
        mb_row.addWidget(self.locate_btn)
        mb_row.addWidget(self.forget_btn)
        mb.addLayout(mb_row)
        self.missing_box.setVisible(False)

        # плашка "есть копии" + что с ними делать
        self.dup_label = QLabel("")
        self.dup_label.setWordWrap(True)
        self.dup_label.setTextFormat(Qt.PlainText)
        self.dup_label.setStyleSheet(
            "background: rgba(250,176,5,35); border: 1px solid #f59f00; border-radius: 6px; padding: 6px;")
        merge_btn = QPushButton("Объединить теги копий")
        merge_btn.setToolTip("Все копии получат одни и те же теги, коллекции и ★")
        merge_btn.clicked.connect(self.merge_copies_tags)
        keep_btn = QPushButton("Оставить в библиотеке только эту")
        keep_btn.setToolTip("Остальные копии уберутся из библиотеки (с диска - нет)\n"
                            "и не вернутся при проверке папок")
        keep_btn.clicked.connect(self.keep_only_this_copy)
        self.trash_btn = QPushButton("🗑 Остальные копии - в Корзину…")
        self.trash_btn.setToolTip("Освободить место: остальные копии уйдут в Корзину Windows,\n"
                                  "откуда их можно вернуть. Теги перейдут к этому файлу.")
        self.trash_btn.clicked.connect(self.trash_other_copies)
        self.dup_box = QWidget()
        db_l = QVBoxLayout(self.dup_box)
        db_l.setContentsMargins(0, 0, 0, 0)
        db_l.addWidget(self.dup_label)
        db_l.addWidget(merge_btn)
        dup_row = QHBoxLayout()
        dup_row.addWidget(keep_btn)
        dup_row.addWidget(self.trash_btn)
        db_l.addLayout(dup_row)
        self.dup_box.setVisible(False)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setFixedHeight(190)

        self.right = QWidget()
        right_layout = QVBoxLayout(self.right)
        right_layout.addWidget(self.preview)
        right_layout.addWidget(self.file_title)
        right_layout.addWidget(self.file_info)
        right_layout.addWidget(self.missing_box)
        right_layout.addWidget(self.dup_box)
        self.stars = StarRating()
        self.stars.rated.connect(lambda v: self.rate_files(self.selected_file_ids(), v))
        fav_row = QHBoxLayout()
        fav_row.addWidget(self.fav_btn, 1)
        fav_row.addWidget(self.stars)
        right_layout.addLayout(fav_row)
        self.edit_tags_btn = QPushButton("🏷 Метки…")
        self.edit_tags_btn.setToolTip("Окно меток как в Steam (Ctrl+T). Работает и для нескольких файлов.")
        self.edit_tags_btn.clicked.connect(self.open_tag_editor)
        tag_input_row = QHBoxLayout()
        tag_input_row.addWidget(self.tag_input, 1)
        tag_input_row.addWidget(self.edit_tags_btn)

        right_layout.addWidget(QLabel("Теги"))
        right_layout.addWidget(self.file_tags_widget)
        right_layout.addLayout(tag_input_row)
        right_layout.addWidget(QLabel("Заметка"))
        self.note_edit = QPlainTextEdit()
        self.note_edit.setPlaceholderText("Заметка к файлу… (ищется поиском: заметка:текст)")
        self.note_edit.setMaximumHeight(90)
        self.note_edit.textChanged.connect(lambda: self.note_timer.start())
        self.note_timer = QTimer(self)
        self.note_timer.setSingleShot(True)
        self.note_timer.setInterval(700)
        self.note_timer.timeout.connect(self.save_note)
        right_layout.addWidget(self.note_edit)
        right_layout.addWidget(QLabel("Коллекции"))
        right_layout.addWidget(self.file_collections_list, 1)

        splitter = self.splitter = QSplitter()
        splitter.addWidget(self.sidebar)
        splitter.addWidget(center)
        splitter.addWidget(self.right)
        splitter.setSizes([265, 735, 285])
        self.setCentralWidget(splitter)

        self.safe_label = QLabel("🛟 Безопасный режим: файлы не проверяются")
        self.safe_label.setStyleSheet("color: #ff922b; font-weight: bold; padding: 0 8px;")
        self.safe_label.setVisible(self.safe_mode)
        self.statusBar().addPermanentWidget(self.safe_label)
        self.apply_grid_size()

        self.setup_shortcuts()

    # ================= сайдбар =================
    def _section(self, title):
        item = QTreeWidgetItem(self.sidebar, [title])
        item.setFlags(Qt.ItemIsEnabled)
        font = item.font(0)
        font.setBold(True)
        font.setPointSize(max(font.pointSize() - 1, 7))
        item.setFont(0, font)
        item.setSizeHint(0, QSize(0, 30))
        return item

    def _add_item(self, parent, text, kind, ident, count):
        item = QTreeWidgetItem(parent, [text, f"{count}"])
        item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
        item.setForeground(1, QBrush(QColor("#8f98a0")))   # счётчик - приглушённо, как в Steam
        item.setToolTip(0, text)
        item.setData(0, Qt.UserRole, kind)
        item.setData(0, Qt.UserRole + 1, ident)
        item.setData(0, Qt.UserRole + 2, text)
        item.setSizeHint(0, QSize(0, 28))
        self._sidebar_items[(kind, ident)] = item
        return item

    def refresh_sidebar(self):
        self.collections = self.db.get_collections()
        self._sidebar_items = {}
        self.sidebar.blockSignals(True)
        self.sidebar.clear()

        lib = self._section("БИБЛИОТЕКА")
        all_item = self._add_item(lib, "Все файлы", "all", 0, self.db.count_files())
        all_item.setToolTip(0, "Все файлы библиотеки.\nПКМ - показать только файлы без тегов, "
                               "без своих тегов или без авто-тегов.")
        self._add_item(lib, "★ Избранное", "fav", 0, self.db.count_files(FileFilter(favorites=True)))
        recent = self._add_item(lib, "🕘 Недавние", "recent", 0, self.db.count_files(FileFilter(recent=True)))
        recent.setToolTip(0, "Файлы, которые ты открывал из программы, - последние сверху.\n"
                             "ПКМ - очистить список.")
        lost = self.db.count_files(FileFilter(missing=True))
        if lost or self.view[0] == "missing":
            item = self._add_item(lib, "⚠ Потерянные", "missing", 0, lost)
            item.setForeground(0, QBrush(QColor("#ff6b6b")))
            item.setToolTip(0, "Файлы, которых сейчас нет на диске: удалены, перемещены туда,\n"
                               "где программа не следит, или диск/флешка отключены.\n"
                               "Записи с тегами сохраняются - файл найдётся, когда вернётся.")
        dups = self.db.count_files(FileFilter(duplicates=True))
        if dups or self.view[0] == "duplicates":
            item = self._add_item(lib, "⧉ Дубликаты", "duplicates", 0, dups)
            groups, extra, wasted = self.db.duplicate_stats()
            item.setToolTip(0, f"Файлы с одинаковым содержимым (сравнивается само содержимое, не имя).\n"
                               f"Групп: {groups}, лишних копий: {extra}, занимают {fmt_size(wasted)}.")

        static = [c for c in self.collections if c["rules"] is None]
        dynamic = [c for c in self.collections if c["rules"] is not None]
        sec = self._section("КОЛЛЕКЦИИ")
        sec.setData(0, Qt.UserRole + 3, "new_static")  # бросить файлы сюда = новая коллекция
        sec.setToolTip(0, "Перетащи сюда файлы - создастся новая коллекция")
        for c in static:
            self._add_item(sec, c["name"], "static", c["id"], self.db.count_files(FileFilter(collection=c)))
        sec = self._section("ДИНАМИЧЕСКИЕ")
        for c in dynamic:
            self._add_item(sec, "⚡ " + c["name"], "dynamic", c["id"],
                           self.db.count_files(FileFilter(collection=c)))
        sec = self._section("ПАПКИ")
        sec.setData(0, Qt.UserRole + 4, "folders_section")
        sec.setToolTip(0, "Папки библиотеки - за ними программа следит. ПКМ - добавить папку")
        for row in self.db.get_folder_rows():
            path = row["path"]
            name = os.path.basename(path.rstrip("\\/")) or path
            item = self._add_item(sec, "📁 " + name, "folder", row["id"],
                                  self.db.count_files(FileFilter(folder=path)))
            item.setToolTip(0, path + "\nПКМ - показать в Проводнике, проверить, убрать из библиотеки")

        self.sidebar.expandAll()
        target = self._sidebar_items.get(self.view)
        if target is None:
            self.view = ("all", 0)
            target = self._sidebar_items[self.view]
        self.sidebar.setCurrentItem(target)
        self.sidebar.blockSignals(False)

    # ---------- перетаскивание файлов на сайдбар ----------
    def on_drop_hint(self, text):
        if text:
            self.statusBar().showMessage(text)
        else:
            self.statusBar().clearMessage()

    def on_files_dropped(self, kind, ident, ids):
        # откладываем: внутри события "бросили" нельзя открывать окна и пересобирать сайдбар
        QTimer.singleShot(0, lambda: self.apply_drop(kind, ident, ids))

    def apply_drop(self, kind, ident, ids):
        n = len(ids)
        if kind == "static":
            name = next((c["name"] for c in self.collections if c["id"] == ident), "?")
            before = self.db.collection_counts_for_files(ids).get(ident, 0)
            self.db.add_to_collection(ids, ident)
            added = n - before
            msg = (f"В коллекцию «{name}» добавлено файлов: {added}" if added
                   else f"Эти файлы уже лежат в «{name}»")
        elif kind == "fav":
            self.db.set_favorite(ids, True)
            msg = f"В избранное добавлено файлов: {n}"
        elif kind == "new_static":
            name, ok = QInputDialog.getText(
                self, "Новая коллекция", f"Название коллекции для файлов ({n}):"
            )
            if not ok or not name.strip():
                return
            cid = self.db.create_collection(name)
            if cid is None:
                QMessageBox.warning(self, "Ошибка", "Коллекция с таким именем уже есть.")
                return
            self.db.add_to_collection(ids, cid)
            msg = f"Создана коллекция «{name.strip()}», файлов: {n}"
        else:
            return
        self.refresh_all()
        self.statusBar().showMessage(msg, 5000)

    def cover_pixmap(self, file_id):
        """Обложка файла для картинки под курсором при перетаскивании из таблицы."""
        f = self.db.get_file(file_id)
        if f is None:
            return None
        base = self.cover_images.get(file_id)
        if base is None:
            base = placeholder_image(f["ext"])
        return QPixmap.fromImage(base)

    def on_sidebar_changed(self, current, _previous):
        if current is None:
            return
        kind = current.data(0, Qt.UserRole)
        if kind is None:  # заголовок секции
            return
        self.view = (kind, current.data(0, Qt.UserRole + 1))
        self.push_history()
        self.refresh_files()

    def current_collection(self):
        kind, ident = self.view
        if kind in ("static", "dynamic"):
            for c in self.collections:
                if c["id"] == ident:
                    return c
        return None

    def on_sidebar_menu(self, pos):
        item = self.sidebar.itemAt(pos)
        if item is None:
            return
        kind = item.data(0, Qt.UserRole)
        if kind == "missing":
            self.on_missing_menu(self.sidebar.viewport().mapToGlobal(pos))
            return
        if item.data(0, Qt.UserRole + 4) == "folders_section":
            menu = QMenu(self)
            act = menu.addAction("📂 Добавить папку…")
            if menu.exec(self.sidebar.viewport().mapToGlobal(pos)) == act:
                self.add_folder()
            return
        if kind == "folder":
            self.on_folder_menu(item.data(0, Qt.UserRole + 1), self.sidebar.viewport().mapToGlobal(pos))
            return
        if kind in ("all", "fav", "recent"):
            self.on_library_menu(kind, self.sidebar.viewport().mapToGlobal(pos))
            return
        if kind not in ("static", "dynamic"):
            return
        cid = item.data(0, Qt.UserRole + 1)
        collection = next(c for c in self.collections if c["id"] == cid)

        menu = QMenu(self)
        act_rename = menu.addAction("Переименовать")
        act_edit = menu.addAction("Изменить правила…") if kind == "dynamic" else None
        act_delete = menu.addAction("Удалить")
        chosen = menu.exec(self.sidebar.viewport().mapToGlobal(pos))

        if chosen is None:
            return
        if chosen == act_rename:
            name, ok = QInputDialog.getText(
                self, "Переименовать", "Новое название:", text=collection["name"]
            )
            if ok and name.strip():
                if not self.db.rename_collection(cid, name):
                    QMessageBox.warning(self, "Ошибка", "Коллекция с таким именем уже есть.")
        elif chosen == act_edit:
            dlg = DynamicCollectionDialog(self.db, self, collection["name"], collection["rules"])
            if dlg.exec() == QDialog.Accepted:
                name, rules = dlg.result_data()
                if name and name != collection["name"]:
                    self.db.rename_collection(cid, name)
                self.db.update_collection_rules(cid, rules)
        elif chosen == act_delete:
            answer = QMessageBox.question(
                self, "Удалить", f"Удалить коллекцию «{collection['name']}»?\nФайлы на диске не пострадают."
            )
            if answer == QMessageBox.Yes:
                self.db.delete_collection(cid)
        self.refresh_sidebar()
        self.refresh_files()

    # ================= плашки-теги (фильтр) =================
    def current_filter(self, with_tags=True):
        return FileFilter(
            include=tuple(self.include) if with_tags else (),
            exclude=tuple(self.exclude) if with_tags else (),
            mode=self.tag_mode,
            search=self.search.text().strip(),
            favorites=self.view[0] == "fav",
            no_tags=self.active_sub_filter() == "no_tags",
            no_user_tags=self.active_sub_filter() == "no_user_tags",
            no_auto_tags=self.active_sub_filter() == "no_auto_tags",
            missing=self.view[0] == "missing",
            duplicates=self.view[0] == "duplicates",
            recent=self.view[0] == "recent",
            folder=(self.db.get_folder_path(self.view[1]) or "") if self.view[0] == "folder" else "",
            collection=self.current_collection(),
        )

    def tag_state(self, tag_id):
        if tag_id in self.include:
            return "include"
        if tag_id in self.exclude:
            return "exclude"
        return "off"

    def refresh_chips(self):
        """Плашки по группам, популярные первыми; пустые прячем (как в Steam)."""
        clear_layout(self.chips_layout)
        facets = self.db.tag_facets(self.current_filter())
        self._tag_paths = self.db.tag_paths()
        valid = {t["id"] for t in facets}
        for d in (self.include, self.exclude):
            for tid in [t for t in d if t not in valid]:
                del d[tid]

        if not facets:
            self.chips_layout.addWidget(QLabel("Тегов пока нет - выбери файл и добавь тег справа"))
            self.update_filter_summary()
            return

        needle = self.chip_search.text().strip().lower()
        active = [t for t in facets if self.tag_state(t["id"]) != "off"]
        others = [
            t for t in facets
            if self.tag_state(t["id"]) == "off" and t["cnt"] > 0
            and (not needle or needle in t["name"].lower())
        ]
        hidden = 0
        if not self.show_all_tags and not needle and len(others) > CHIP_LIMIT:
            hidden = len(others) - CHIP_LIMIT
            others = others[:CHIP_LIMIT]   # facets уже отсортированы по популярности
        if needle:
            active = [t for t in active if needle in t["name"].lower()] or active

        # выбранные - первыми, дальше по группам: свои метки, группы по алфавиту, "Тип файла"
        def group_key(t):
            g = t["grp"]
            return (0 if not g else 2 if g == AUTO_GROUP else 1, g.lower())

        shown = sorted(others, key=lambda t: (group_key(t), -t["cnt"], t["name"].lower()))
        if active:
            self.chips_layout.addWidget(make_group_label("Выбрано:"))
            for t in active:
                self._add_filter_chip(t)
        last_group = None
        for t in shown:
            g = t["grp"] or NO_GROUP
            if g != last_group:
                self.chips_layout.addWidget(make_group_label(g + ":"))
                last_group = g
            self._add_filter_chip(t)

        if hidden or self.show_all_tags:
            more = QPushButton(f"Ещё {hidden} ▾" if hidden else "Свернуть ▴")
            more.setFlat(True)
            more.setCursor(Qt.PointingHandCursor)
            more.clicked.connect(self.toggle_show_all_tags)
            self.chips_layout.addWidget(more)
        if needle and not shown and not active:
            self.chips_layout.addWidget(QLabel("Не найдено"))
        self.update_filter_summary()

    def _add_filter_chip(self, tag):
        tid, name = tag["id"], tag["name"]
        state = self.tag_state(tid)
        text = name if state == "exclude" else f"{name}  {tag['cnt']}"
        chip = make_filter_chip(text, tag["color"], state, icon=badge_icon(tag))
        tips = {"off": "Клик - нужен этот тег", "include": "Клик - исключить тег",
                "exclude": "Клик - убрать из фильтра"}
        path = getattr(self, "_tag_paths", {}).get(tid, name)
        nested = "\nВключает вложенные теги" if self.db.get_children(tid) else ""
        chip.setToolTip(path + (f"  ·  {tag['grp']}" if tag["grp"] else "") + nested + "\n" + tips[state])
        chip.clicked.connect(lambda _=False, t=tid: self.cycle_tag(t))
        chip.setContextMenuPolicy(Qt.CustomContextMenu)
        chip.customContextMenuRequested.connect(
            lambda pos, t=tid, w=chip: self.on_chip_menu(t, w.mapToGlobal(pos))
        )
        self.chips_layout.addWidget(chip)

    def update_filter_summary(self):
        names = {t["id"]: t["name"] for t in self.db.get_tags_with_counts()}
        parts = []
        if self.include:
            joiner = " или " if self.tag_mode == "any" else " и "
            parts.append(joiner.join(names.get(t, "?") for t in self.include))
        if self.exclude:
            parts.append("без: " + ", ".join(names.get(t, "?") for t in self.exclude))
        self.filter_summary.setText("   ".join(parts))
        self.reset_btn.setVisible(bool(self.include or self.exclude))

    def set_tag_state(self, tag_id, state):
        self.include.pop(tag_id, None)
        self.exclude.pop(tag_id, None)
        if state == "include":
            self.include[tag_id] = True
        elif state == "exclude":
            self.exclude[tag_id] = True
        self.refresh_files()

    def cycle_tag(self, tag_id):
        nxt = {"off": "include", "include": "exclude", "exclude": "off"}
        self.set_tag_state(tag_id, nxt[self.tag_state(tag_id)])

    def show_only_tag(self, tag_id):
        """Как ссылка на тег в Steam: показать все файлы с этим тегом."""
        self.include = {tag_id: True}
        self.exclude = {}
        self.chip_search.clear()
        self.refresh_files()

    def on_mode_changed(self):
        self.tag_mode = self.mode_box.currentData()
        self.refresh_files()

    def toggle_show_all_tags(self):
        self.show_all_tags = not self.show_all_tags
        self.refresh_chips()

    def reset_tag_filter(self):
        self.include.clear()
        self.exclude.clear()
        self.refresh_files()

    def on_chip_menu(self, tag_id, global_pos):
        tag = self.db.get_tag(tag_id)
        if tag is None:
            return
        state = self.tag_state(tag_id)
        menu = QMenu(self)
        act_only = menu.addAction("Показать только этот тег")
        act_inc = menu.addAction("✓ Нужен")
        act_exc = menu.addAction("✕ Исключить")
        act_off = menu.addAction("Убрать из фильтра")
        act_inc.setEnabled(state != "include")
        act_exc.setEnabled(state != "exclude")
        act_off.setEnabled(state != "off")
        menu.addSeparator()
        ids = self.selected_file_ids()
        act_put = menu.addAction(f"Поставить выделенным файлам ({len(ids)})")
        act_put.setEnabled(bool(ids))
        menu.addSeparator()
        act_rename = menu.addAction("Переименовать…")
        act_color = menu.addAction("🖼 Цвет и значок…")
        act_group = menu.addAction("Группа…")
        act_nest = menu.addAction("↳ Вложить в другой тег…")
        act_child = menu.addAction("＋ Вложенный тег…")
        act_delete = menu.addAction("Удалить тег")
        chosen = menu.exec(global_pos)
        if chosen is None:
            return
        if chosen == act_only:
            self.show_only_tag(tag_id)
        elif chosen in (act_inc, act_exc, act_off):
            self.set_tag_state(
                tag_id, {act_inc: "include", act_exc: "exclude", act_off: "off"}[chosen]
            )
        elif chosen == act_put:
            self.db.tag_files(ids, tag_id)
            self.refresh_files()
        elif chosen == act_rename:
            new, ok = QInputDialog.getText(self, "Переименовать тег", "Новое название:", text=tag["name"])
            if ok and not self.db.rename_tag(tag_id, new):
                QMessageBox.warning(self, "Ошибка", "Такой тег уже есть (или название пустое).")
            self.refresh_all()
        elif chosen == act_color:
            dlg = TagIconDialog(self.db, tag_id, self)
            if dlg.exec() == QDialog.Accepted:
                self.checkpoint(f"значок тега «{tag['name']}»")
                dlg.apply()
                self.refresh_files()
        elif chosen == act_nest:
            ok, parent_id = choose_parent(self, self.db, [tag_id])
            if ok:
                self.db.set_parent(tag_id, parent_id)
                self.refresh_files()
        elif chosen == act_child:
            name, ok = QInputDialog.getText(self, "Вложенный тег", f"Новый тег внутри «{tag['name']}»:")
            if ok and name.strip():
                self.db.set_parent(self.db.ensure_tag(name), tag_id)
                self.refresh_files()
        elif chosen == act_group:
            groups = [""] + self.db.get_groups()
            current = groups.index(tag["grp"]) if tag["grp"] in groups else 0
            grp, ok = QInputDialog.getItem(
                self, "Группа тега", "Группа (можно вписать новую, пусто - без группы):",
                groups, current, True,
            )
            if ok:
                self.db.set_tag_group(tag_id, grp)
                self.refresh_files()
        elif chosen == act_delete:
            answer = QMessageBox.question(
                self, "Удалить тег", f"Удалить тег «{tag['name']}» у всех файлов?"
            )
            if answer == QMessageBox.Yes:
                self.db.delete_tag(tag_id)
                self.refresh_all()

    def open_tag_manager(self):
        TagManagerDialog(self.db, self).exec()
        self.refresh_all()

    # ================= список файлов =================
    def selected_file_ids(self):
        """id выделенных файлов в порядке списка."""
        if self.mode == "grid":
            items = sorted(self.grid.selectedItems(), key=self.grid.row)
            return [i.data(Qt.UserRole) for i in items]
        rows = sorted({i.row() for i in self.table.selectedItems()})
        return [self.table.item(r, COL_NAME).data(Qt.UserRole) for r in rows]

    def current_file_id(self):
        ids = self.selected_file_ids()
        return ids[0] if ids else None

    def refresh_files(self):
        self.reload(self.selected_file_ids())

    def refresh_all(self):
        self.refresh_sidebar()
        self.refresh_files()

    def reload(self, keep):
        keep = set(keep or ())
        # в «Дубликатах» копии стоят рядом, иначе - выбранная сортировка
        sort = {"duplicates": "dups", "recent": "recent"}.get(self.view[0], self.sort_key)
        self._tags_map = {t["id"]: t for t in self.db.get_tags_with_counts()}
        all_files = self.db.query_files(self.current_filter(), sort=sort)
        # новый фильтр/раздел - снова показываем с начала
        sig = (self.view, self.sub_filter, self.search.text(), tuple(self.include), tuple(self.exclude), self.tag_mode, sort)
        if sig != self._filter_sig:
            self._filter_sig = sig
            self.page_limit = self.page_size()
        total = len(all_files)
        files = all_files[:self.page_limit]
        if self.mode == "grid":
            self.fill_grid(files, keep)
        else:
            self.fill_table(files, keep)
        left = total - len(files)
        self.more_btn.setVisible(left > 0)
        if left > 0:
            self.more_btn.setText(f"Показано {len(files):,} из {total:,}  -  показать ещё {min(self.page_size(), left):,}"
                                  .replace(",", " "))
        self.refresh_chips()
        self.refresh_file_panel()
        self.update_search_hint()
        self.update_sub_indicator()
        self.update_tag_hint()
        self.update_empty_state(total)
        self.statusBar().showMessage(f"Файлов: {total}")

    def fill_table(self, files, keep):
        self.table.blockSignals(True)
        self.table.clearSelection()
        self.table.setRowCount(len(files))
        first = None
        for row, f in enumerate(files):
            fav = QTableWidgetItem("★" if f["favorite"] else "")
            fav.setTextAlignment(Qt.AlignCenter)
            lost = f["missing_since"] is not None
            name = QTableWidgetItem(("⚠ " if lost else "") + f["name"])
            name.setData(Qt.UserRole, f["id"])
            if lost:
                name.setForeground(QBrush(QColor("#ff6b6b")))
                name.setToolTip("Файла нет на диске")
            self.table.setItem(row, COL_FAV, fav)
            self.table.setItem(row, COL_NAME, name)
            self.table.setItem(row, COL_TAGS, QTableWidgetItem(f["tags_text"] or ""))
            self.table.setItem(row, COL_SIZE, QTableWidgetItem(fmt_size(f["size"])))
            self.table.setItem(row, COL_PATH, QTableWidgetItem(f["path"]))
            rating = QTableWidgetItem(stars_text(f["rating"]))
            rating.setForeground(QBrush(QColor("#fab005")))
            self.table.setItem(row, COL_RATING, rating)
        sel = self.table.selectionModel()
        for row, f in enumerate(files):
            if f["id"] in keep:
                index = self.table.model().index(row, 0)
                sel.select(index, QItemSelectionModel.Select | QItemSelectionModel.Rows)
                if first is None:
                    first = row
        if first is not None:
            self.table.scrollToItem(self.table.item(first, COL_NAME))
        self.table.blockSignals(False)

    # ---------- режим "сетка" (обложки) ----------
    # v1.4: на 2000+ картинках сетка съедала сотни мегабайт и вылетала - каждая плитка сразу
    # получала полноразмерную обложку, а превью грузились для всех файлов разом. Теперь:
    #   * невидимые плитки - одна общая заглушка на тип файла (почти не занимает памяти);
    #   * настоящие обложки рисуются только для видимых плиток (+ экран сверху и снизу),
    #     в размере плитки, и пересчитываются при прокрутке;
    #   * превью грузятся только для видимых, очередь сбрасывается при прокрутке;
    #   * все кэши обложек ограничены (LRU), дальние плитки возвращаются к заглушке.
    def fill_grid(self, files, keep):
        self.thumbs.reset()
        self.grid.blockSignals(True)
        self.grid.setUpdatesEnabled(False)
        self.grid.clear()
        self.grid_items = {}
        self._real_icons = set()
        first = None
        for f in files:
            colors = [c for c in (f["tag_colors"] or "").split(",") if c]
            lost = f["missing_since"] is not None
            tag_ids = [int(x) for x in (f["tag_ids"] or "").split(",") if x]
            shown, hidden = order_badges(tag_ids, self._tags_map, int(self.settings["cover_badges"]))
            self.cover_meta[f["id"]] = (bool(f["favorite"]), colors, f["ext"], lost, shown, hidden,
                                        f["rating"] or 0, f["path"])
            item = QListWidgetItem(f["name"])
            item.setData(Qt.UserRole, f["id"])
            tags = f"\n🏷 {f['tags_text']}" if f["tags_text"] else ""
            warn = "\n⚠ Файла нет на диске" if lost else ""
            stars = f"\n{stars_text(f['rating'])}" if f["rating"] else ""
            note = f"\n📝 {f['note'][:120]}" if f["note"] else ""
            item.setToolTip(f"{f['name']}\n{fmt_size(f['size'])}{stars}{tags}{note}{warn}")
            item.setIcon(self.placeholder_icon(f["id"]))
            self.grid.addItem(item)
            self.grid_items[f["id"]] = item
            if f["id"] in keep:
                item.setSelected(True)
                if first is None:
                    first = item
        if first is not None:
            self.grid.setCurrentItem(first, QItemSelectionModel.NoUpdate)
            self.grid.scrollToItem(first)
        self.grid.setUpdatesEnabled(True)
        self.grid.blockSignals(False)
        self.schedule_covers(now=True)

    def _cover_px_size(self):
        """Размер обложки в пикселях экрана (с учётом масштаба Windows)."""
        size = self.grid.iconSize()
        try:
            dpr = float(self.grid.devicePixelRatioF()) or 1.0
        except (AttributeError, TypeError):
            dpr = 1.0
        w = max(16, min(COVER_W, int(size.width() * dpr)))
        h = max(12, min(COVER_H, int(size.height() * dpr)))
        return w, h, dpr

    def placeholder_icon(self, file_id):
        """Общая заглушка для невидимых плиток: одна иконка на тип файла."""
        meta = self.cover_meta[file_id]
        ext, lost = meta[2], meta[3]
        loading = ext in PREVIEW_EXTS and not lost
        w, h, dpr = self._cover_px_size()
        key = (ext, loading, w, h)
        icon = self._placeholder_icons.get(key)
        if icon is None:
            pix = QPixmap.fromImage(placeholder_image(ext, loading=loading)
                                    .scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            pix.setDevicePixelRatio(dpr)
            icon = self._placeholder_icons[key] = QIcon(pix)
        return icon

    def make_cover(self, file_id):
        favorite, colors, ext, lost, shown, hidden, rating = self.cover_meta[file_id][:7]
        base = self.cover_images.get(file_id)
        w, h, dpr = self._cover_px_size()
        # готовые обложки кэшируем: клик по тегу не перерисовывает тысячи картинок заново
        key = (file_id, favorite, tuple(colors), lost, base is not None, badges_key(shown, hidden), rating, w, h)
        pix = self.cover_cache.get(key)
        if pix is not None:
            self.cover_cache.move_to_end(key)
            return pix
        if base is None:
            base = placeholder_image(ext, loading=ext in PREVIEW_EXTS and not lost)
        pix = compose_cover(base, favorite, colors if self.settings["cover_strip"] else [],
                            missing=lost, badges=shown, hidden=hidden,
                            rating=rating if self.settings["cover_stars"] else 0)
        if w < COVER_W or h < COVER_H:   # храним в размере плитки, а не 320×240
            pix = pix.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pix.setDevicePixelRatio(dpr)
        self.cover_cache[key] = pix
        while len(self.cover_cache) > COVER_CACHE_LIMIT:
            self.cover_cache.popitem(last=False)
        return pix

    def schedule_covers(self, *_args, now=False):
        if self.mode != "grid":
            return
        self._covers_timer.start(0 if now else 60)

    def visible_grid_range(self):
        """Номера первой и последней видимой плитки. Плитки идут по строкам сверху вниз,
        поэтому первую видимую ищем двоичным поиском - быстро даже на 10 000 файлов."""
        n = self.grid.count()
        if n == 0:
            return 0, -1
        vp = self.grid.viewport().rect()
        if vp.height() <= 0:
            return 0, min(n, 60) - 1
        lo, hi = 0, n - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if self.grid.visualItemRect(self.grid.item(mid)).bottom() < vp.top():
                lo = mid + 1
            else:
                hi = mid
        last = lo
        while last + 1 < n and self.grid.visualItemRect(self.grid.item(last + 1)).top() <= vp.bottom():
            last += 1
        return lo, last

    def load_visible_covers(self):
        if self.mode != "grid" or not self.grid_items:
            return
        first, last = self.visible_grid_range()
        if last < first:
            return
        n = self.grid.count()
        margin = last - first + 1                      # ещё по экрану сверху и снизу
        lo, hi = max(0, first - margin), min(n - 1, last + margin)
        order = list(range(first, last + 1)) + list(range(last + 1, hi + 1)) + list(range(first - 1, lo - 1, -1))
        self.thumbs.reset()                            # то, что уже прокрутили, не грузим
        window = set()
        for i in order:
            item = self.grid.item(i)
            fid = item.data(Qt.UserRole)
            if fid not in self.cover_meta:
                continue
            window.add(fid)
            meta = self.cover_meta[fid]
            if fid not in self._real_icons:
                item.setIcon(QIcon(self.make_cover(fid)))
                self._real_icons.add(fid)
            if meta[2] in PREVIEW_EXTS and not meta[3] and fid not in self.cover_images:
                self.thumbs.request(fid, meta[7])
        if len(self._real_icons) > REAL_ICONS_LIMIT:   # дальние плитки - обратно к заглушке
            for fid in list(self._real_icons - window):
                item = self.grid_items.get(fid)
                if item is not None:
                    item.setIcon(self.placeholder_icon(fid))
                self._real_icons.discard(fid)

    def on_cover_loaded(self, file_id, image):
        """Фоновая загрузка закончила превью - подставляем его в сетку."""
        self.cover_images[file_id] = image
        self.cover_images.move_to_end(file_id)
        while len(self.cover_images) > COVER_IMAGES_LIMIT:
            self.cover_images.popitem(last=False)
        item = self.grid_items.get(file_id)
        if item is not None and self.mode == "grid" and file_id in self._real_icons:
            item.setIcon(QIcon(self.make_cover(file_id)))
            if file_id == self.current_file_id() and len(self.selected_file_ids()) == 1:
                self.show_preview(self.db.get_file(file_id))

    def apply_grid_size(self):
        w = self.size_slider.value()
        h = w * 3 // 4
        self.grid.setIconSize(QSize(w, h))
        self.grid.setGridSize(QSize(w + 16, h + 36))
        # новый размер - обложки перерисуем (с задержкой, чтобы не тормозить на ползунке)
        self._size_timer.start(150)

    def _regrid_covers(self):
        self._placeholder_icons.clear()
        for fid, item in self.grid_items.items():
            if fid in self.cover_meta:
                item.setIcon(self.placeholder_icon(fid))
        self._real_icons = set()
        self.schedule_covers(now=True)

    def set_mode(self, mode):
        self.update_view_toggle(mode)
        if mode == self.mode:
            return
        keep = self.selected_file_ids()
        self.mode = mode
        self.views.setCurrentIndex(0 if mode == "grid" else 1)
        self.update_view_toggle(mode)
        self.reload(keep)

    def update_view_toggle(self, mode):
        # одна кнопка: показывает, на что переключит; ползунок обложек - только в сетке
        self.view_btn.setText("☰" if mode == "grid" else "▦")
        self.view_btn.setToolTip("Показать списком  (Ctrl+2)" if mode == "grid" else "Показать сеткой  (Ctrl+1)")
        self.size_slider.setVisible(mode == "grid")

    def on_sort_changed(self):
        self.sort_key = self.sort_box.currentData()
        self.refresh_files()

    def on_grid_double_click(self, item):
        f = self.db.get_file(item.data(Qt.UserRole))
        if f is not None:
            self.open_path(f["path"])

    def show_preview(self, f):
        """Большая обложка справа (для картинок - настоящая картинка)."""
        if f is None:
            self.preview.clear()
            return
        pix = None
        if f["ext"] in IMAGE_EXTS and os.path.exists(f["path"]):
            reader = QImageReader(f["path"])
            reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid():
                size.scale(256, 190, Qt.KeepAspectRatio)
                reader.setScaledSize(size)
            img = reader.read()
            if not img.isNull():
                pix = QPixmap.fromImage(img)
        if pix is None:
            pix = QPixmap.fromImage(placeholder_image(f["ext"])).scaled(
                253, 190, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        self.preview.setPixmap(pix)

    def on_double_click(self, row, _col):
        self.open_path(self.table.item(row, COL_PATH).text())

    def open_path(self, path):
        if os.path.exists(path):
            os.startfile(path)  # только Windows
            self.db.mark_opened_path(path)
            if self.view[0] == "recent":
                self.refresh_files()
        else:
            self.on_path_gone()

    def reveal(self, path):
        if os.path.exists(path):
            subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')
        else:
            self.on_path_gone()

    def on_path_gone(self):
        """Файла не оказалось на месте - сразу перепроверяем: может, он просто переехал."""
        self.statusBar().showMessage("Файл не найден - ищу, куда он делся…")
        self.check_files(manual=True)

    def on_table_menu(self, pos):
        item = self.table.itemAt(pos)
        if item is None:
            return
        if not self.table.item(item.row(), COL_NAME).isSelected():
            self.table.selectRow(item.row())
        self.show_file_menu(self.table.viewport().mapToGlobal(pos))

    def on_grid_menu(self, pos):
        item = self.grid.itemAt(pos)
        if item is None:
            return
        if not item.isSelected():
            self.grid.setCurrentItem(item)
        self.show_file_menu(self.grid.viewport().mapToGlobal(pos))

    def show_file_menu(self, global_pos):
        ids = self.selected_file_ids()
        if not ids:
            return
        files = self.db.get_files(ids)
        n = len(ids)
        first = next(f for f in files if f["id"] == ids[0])
        all_fav = all(f["favorite"] for f in files)

        lost = [f["id"] for f in files if f["missing_since"] is not None]
        menu = QMenu(self)
        if n == 1 and not lost:
            menu.addAction("Открыть\tEnter").triggered.connect(lambda: self.open_path(first["path"]))
            menu.addAction("👁 Быстрый просмотр\tПробел").triggered.connect(self.open_quick_view)
            menu.addAction("Показать в папке\tCtrl+E").triggered.connect(lambda: self.reveal(first["path"]))
            menu.addSeparator()
        if n == 1 and not lost and self.db.copies_of(ids[0]):
            menu.addAction("⧉ Показать все дубликаты").triggered.connect(self.show_duplicates_view)
            menu.addSeparator()
        if n == 1 and lost:
            menu.addAction("🔍 Найти вручную…").triggered.connect(self.locate_selected)
            menu.addSeparator()
        menu.addAction(f"🏷 Метки…{'' if n == 1 else f' ({n} файлов)'}\tCtrl+T").triggered.connect(
            self.open_tag_editor
        )

        # быстрые теги: популярные + у выделенных (как подсказки в Steam)
        quick = menu.addMenu("Быстрый тег")
        have = {t["id"]: t["cnt"] for t in self.db.get_tags_for_files(ids)}
        tags = [t for t in self.db.get_tags_with_counts() if not t["is_auto"]][:15]
        quick.setEnabled(bool(tags))
        for t in tags:
            act = quick.addAction(t["name"])
            act.setCheckable(True)
            act.setChecked(have.get(t["id"], 0) == n)
            act.triggered.connect(
                lambda checked, tid=t["id"]: self.set_tag_on_selection(tid, checked)
            )

        rate_menu = menu.addMenu("Оценка")
        for v in range(5, -1, -1):
            rate_menu.addAction(f"{stars_text(v) if v else 'Без оценки'}\t{v}").triggered.connect(
                lambda _=False, r=v: self.rate_files(self.selected_file_ids(), r))
        if not lost:
            menu.addAction(f"✏ Переименовать{'' if n == 1 else f' ({n})'}…\tF2").triggered.connect(
                self.rename_selected)
        menu.addSeparator()
        menu.addAction("Убрать из избранного" if all_fav else "★ В избранное").triggered.connect(
            lambda: self.toggle_favorite(ids, not all_fav)
        )
        sub = menu.addMenu("Добавить в коллекцию")
        static = [c for c in self.collections if c["rules"] is None]
        sub.setEnabled(bool(static))
        counts = self.db.collection_counts_for_files(ids)
        for c in static:
            act = sub.addAction(c["name"])
            act.setCheckable(True)
            act.setChecked(counts.get(c["id"], 0) == n)
            act.triggered.connect(lambda checked, cid=c["id"]: self.set_in_collection(ids, cid, checked))
        menu.addSeparator()
        menu.addAction(f"Убрать из библиотеки{'' if n == 1 else f' ({n})'}").triggered.connect(
            self.remove_selected_from_library
        )
        menu.exec(global_pos)

    def set_tag_on_selection(self, tag_id, on):
        ids = self.selected_file_ids()
        if not ids:
            return
        if on:
            self.db.tag_files(ids, tag_id)
        else:
            self.db.untag_files(ids, tag_id)
        self.refresh_all()

    def open_tag_editor(self):
        ids = self.selected_file_ids()
        if not ids:
            self.statusBar().showMessage("Сначала выдели файл(ы)")
            return
        dlg = TagEditorDialog(self.db, ids, self)
        if dlg.exec() == QDialog.Accepted:
            dlg.apply()
        self.refresh_all()  # даже при отмене: в окне могли создать новый тег

    # ================= панель деталей =================
    def refresh_file_panel(self):
        self.flush_note()
        ids = self.selected_file_ids()
        clear_layout(self.file_tags_layout)
        self.file_collections_list.blockSignals(True)
        self.file_collections_list.clear()
        self.right.setEnabled(bool(ids))
        self.preview.setVisible(bool(ids))
        self.completer_model.setStringList([t["name"] for t in self.db.get_tags_with_counts()])

        if not ids:
            self.file_title.setText("Выбери файл")
            self.file_info.setText("Ctrl / Shift + клик - выделить несколько")
            self.show_preview(None)
            self.fav_btn.setChecked(False)
            self.fav_btn.setText("☆ В избранное")
            self.missing_box.setVisible(False)
            self.dup_box.setVisible(False)
            self.stars.setRating(0)
            self.load_note(None)
            self.file_collections_list.blockSignals(False)
            return

        n = len(ids)
        files = self.db.get_files(ids)
        all_fav = all(f["favorite"] for f in files)
        if n == 1:
            f = files[0]
            self.file_title.setText(f["name"])
            self.show_preview(f)
            self.file_info.setText(f"{fmt_size(f['size'])}\n{f['path']}")
        else:
            self.file_title.setText(f"Выделено файлов: {n}")
            self.show_preview(None)
            total = sum(f["size"] for f in files)
            self.file_info.setText(f"Всего {fmt_size(total)}\nТеги и коллекции меняются сразу у всех")
        self.fav_btn.setChecked(all_fav)
        self.fav_btn.setText("★ В избранном" if all_fav else "☆ В избранное")
        ratings = {f["rating"] or 0 for f in files}
        self.stars.setRating(ratings.pop() if len(ratings) == 1 else 0)
        self.load_note(files[0] if n == 1 else None, multi=n > 1)

        copies = self.db.copies_of(ids[0]) if n == 1 else []
        self.dup_box.setVisible(bool(copies))
        if copies:
            lines = "\n".join("• " + c["path"] for c in copies[:6])
            more = f"\n…и ещё {len(copies) - 6}" if len(copies) > 6 else ""
            self.dup_label.setText(f"⧉ У файла есть копии с тем же содержимым: {len(copies)}\n{lines}{more}")
            self.trash_btn.setEnabled(trash.available())

        lost = [f for f in files if f["missing_since"] is not None]
        self.missing_box.setVisible(bool(lost))
        if lost:
            if n == 1:
                self.missing_label.setText(
                    f"⚠ Файла нет на диске (замечено {fmt_date(lost[0]['missing_since'])}).\n"
                    "Удалён, перемещён туда, где программа не следит, или диск отключён."
                )
            else:
                self.missing_label.setText(f"⚠ Нет на диске: {len(lost)} из {n}")
            self.locate_btn.setVisible(n == 1)

        tags = self.db.get_tags_for_files(ids)
        paths = self.db.tag_paths()
        if not tags:
            empty = QLabel("Тегов нет")
            empty.setStyleSheet("color: #868e96;")
            self.file_tags_layout.addWidget(empty)
        for tag in tags:
            partial = tag["cnt"] < n
            text = f"{tag['name']}  {tag['cnt']}/{n}" if partial else tag["name"]
            chip = TagChip(text, tag["color"], partial=partial, icon=badge_icon(tag))
            path = paths.get(tag["id"], tag["name"])
            chip.setToolTip(path + ("\nЭтот тег есть не у всех выделенных файлов" if partial else ""))
            chip.clicked.connect(lambda t=tag["id"]: self.show_only_tag(t))
            chip.removed.connect(lambda t=tag["id"]: self.on_remove_tag(t))
            self.file_tags_layout.addWidget(chip)

        counts = self.db.collection_counts_for_files(ids)
        for c in self.collections:
            if c["rules"] is None:
                item = QListWidgetItem(c["name"])
                item.setData(Qt.UserRole, c["id"])
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                k = counts.get(c["id"], 0)
                item.setCheckState(Qt.Checked if k == n else (Qt.PartiallyChecked if k else Qt.Unchecked))
                self.file_collections_list.addItem(item)
        self.file_collections_list.blockSignals(False)

    def on_tag_input(self):
        ids = self.selected_file_ids()
        name = self.tag_input.text().strip()
        if not ids or not name:
            return
        tag_id = self.db.ensure_tag(name)
        self.db.tag_files(ids, tag_id)
        self.tag_input.clear()
        self.refresh_all()

    def on_remove_tag(self, tag_id):
        ids = self.selected_file_ids()
        if not ids:
            return
        self.db.untag_files(ids, tag_id)
        self.refresh_all()

    def on_fav_clicked(self):
        ids = self.selected_file_ids()
        if ids:
            self.toggle_favorite(ids, self.fav_btn.isChecked())

    def toggle_favorite(self, file_ids, value):
        self.db.set_favorite(file_ids, value)
        self.refresh_all()

    def on_file_collection_toggled(self, item):
        ids = self.selected_file_ids()
        if ids:
            self.set_in_collection(ids, item.data(Qt.UserRole), item.checkState() != Qt.Unchecked)

    def set_in_collection(self, file_ids, collection_id, on):
        if on:
            self.db.add_to_collection(file_ids, collection_id)
        else:
            self.db.remove_from_collection(file_ids, collection_id)
        self.refresh_all()

    # ================= действия тулбара =================
    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Выбери папку")
        if folder:
            self.start_add_folder(folder)

    # ---------- файлы на диске ----------
    def check_files(self, manual=True):
        self.statusBar().showMessage("Проверяю файлы на диске…")
        self.watcher.check_all(manual=manual)

    def on_files_checked(self, report, manual):
        if report.changed:
            self.refresh_all()
        if report.moved:
            self.show_moved_notice(report.moved_items or [], report.moved)
        if report.changed or manual:
            self.statusBar().showMessage(report.text(), 8000)
        # после проверки - тихо досчитать отпечатки дубликатов и цвета картинок (только новое)
        self.scan_duplicates(manual=False)
        self.scan_colors()

    # ---------- дубликаты ----------
    def scan_duplicates(self, manual=False):
        if self._dup_running or (not manual and not self.settings["auto_duplicates"]):
            return
        candidates = [tuple(r) for r in self.db.dup_candidates()]
        self._dup_running = True
        if manual:
            self.statusBar().showMessage("Ищу дубликаты: сравниваю содержимое файлов одного размера…")
        self.background.run(find_duplicate_hashes, (candidates,),
                            lambda result, m=manual: self.on_duplicates_scanned(result, m))

    def on_duplicates_scanned(self, result, manual):
        self._dup_running = False
        if isinstance(result, Exception):
            if manual:
                self.statusBar().showMessage(f"Поиск дубликатов не удался: {result}", 8000)
            return
        if result:
            self.db.save_hashes(result)
            self.refresh_all()
        if manual:
            groups, extra, wasted = self.db.duplicate_stats()
            if groups:
                self.show_duplicates_view()  # сначала переключаемся, потом пишем итог - иначе затрётся
                self.statusBar().showMessage(
                    f"Дубликаты: групп {groups}, лишних копий {extra}, занимают {fmt_size(wasted)}", 10000)
            else:
                self.statusBar().showMessage("Дубликатов не найдено", 8000)

    def show_duplicates_view(self):
        self.view = ("duplicates", 0)
        self.refresh_all()

    def _copy_ids(self):
        fid = self.current_file_id()
        return fid, [c["id"] for c in self.db.copies_of(fid)] if fid is not None else []

    def merge_copies_tags(self):
        fid, others = self._copy_ids()
        if others:
            self.db.merge_copy_tags([fid, *others])
            self.refresh_all()
            self.statusBar().showMessage(f"Теги объединены у копий: {len(others) + 1}", 6000)

    def keep_only_this_copy(self):
        fid, others = self._copy_ids()
        if not others:
            return
        answer = QMessageBox.question(
            self, "Оставить только эту копию",
            f"Убрать из библиотеки остальные копии ({len(others)})?\n"
            "Их теги перейдут к этому файлу. С диска ничего не удаляется.",
        )
        if answer != QMessageBox.Yes:
            return
        backup.make_backup(self.db.conn, "remove-dups")
        self.db.merge_copy_tags([fid, *others])
        self.db.remove_files(others)
        self.reload([fid])
        self.refresh_sidebar()

    def trash_other_copies(self):
        fid, others = self._copy_ids()
        if not others:
            return
        rows = self.db.get_files(others)
        total = sum(r["size"] for r in rows)
        listing = "\n".join(r["path"] for r in rows[:10]) + ("\n…" if len(rows) > 10 else "")
        answer = QMessageBox.question(
            self, "Копии - в Корзину",
            f"Отправить в Корзину Windows копии ({len(rows)}, {fmt_size(total)})?\n\n{listing}\n\n"
            "Этот файл останется. Теги копий перейдут к нему. Вернуть копии можно из Корзины.",
        )
        if answer != QMessageBox.Yes:
            return
        backup.make_backup(self.db.conn, "remove-dups")
        self.db.merge_copy_tags([fid, *others])
        done, failed = [], []
        for r in rows:
            try:
                trash.to_trash(r["path"])
                done.append(r["id"])
            except OSError as exc:
                failed.append(f"{r['path']}: {exc}")
        if done:
            self.db.remove_files(done, hide=False)  # файла больше нет - скрывать нечего
        self.reload([fid])
        self.refresh_sidebar()
        if failed:
            QMessageBox.warning(self, "Корзина", "Не получилось:\n" + "\n".join(failed[:10]))
        else:
            self.statusBar().showMessage(
                f"В Корзину отправлено копий: {len(done)}, освобождено {fmt_size(total)}", 8000)

    def open_library_folders(self):
        dlg = LibraryFoldersDialog(self.db, self)
        dlg.exec()
        if dlg.requested_add:
            self.start_add_folder(dlg.requested_add)
        elif dlg.changed:
            self.refresh_all()
            if not self.safe_mode:
                self.check_files(manual=False)

    def locate_selected(self):
        """Файл потерян: ищем похожие в фоне и предлагаем варианты (или показать вручную)."""
        file_id = self.current_file_id()
        if file_id is None:
            return
        f = self.db.get_file(file_id)
        start = os.path.dirname(f["path"])
        while start and not os.path.isdir(start):  # ближайшая существующая папка
            parent = os.path.dirname(start)
            start = "" if parent == start else parent
        home = os.path.expanduser("~")
        dirs = [d for d in [start, *self.db.get_folders(),
                            *(os.path.join(home, x) for x in ("Desktop", "Downloads", "Documents"))]
                if d and os.path.isdir(d)]
        known = [p for _i, p in self.db.all_paths()]
        self.statusBar().showMessage(f"Ищу, куда делся «{f['name']}»…")
        self.locate_btn.setEnabled(False)
        self.background.run(
            find_candidates, (f["name"], f["size"], f["ext"], dirs, known),
            lambda result, fid=file_id, start=start: self.on_candidates(fid, start, result),
        )

    def on_candidates(self, file_id, start_dir, result):
        self.locate_btn.setEnabled(True)
        self.statusBar().clearMessage()
        f = self.db.get_file(file_id)
        if f is None:
            return
        candidates = [] if isinstance(result, Exception) else result
        dlg = CandidatesDialog(f, candidates, self)
        dlg.start_dir = start_dir
        if dlg.exec() != QDialog.Accepted or not dlg.chosen:
            return
        kept = self.db.relink(file_id, dlg.chosen)
        self.statusBar().showMessage(
            f"Нашёлся: {os.path.normpath(dlg.chosen)}. Теги и коллекции на месте.", 8000)
        self.reload([kept])
        self.refresh_sidebar()

    def remove_selected_from_library(self):
        ids = self.selected_file_ids()
        if not ids:
            return
        answer = QMessageBox.Yes if not self.settings["confirm_remove"] else QMessageBox.question(
            self, "Убрать из библиотеки",
            f"Убрать из библиотеки файлов: {len(ids)}?\n"
            "Их теги и место в коллекциях забудутся. Файлы на диске не пострадают.\n\n"
            "Проверка папок не вернёт их обратно. Передумал - «☰ Ещё → Папки библиотеки →\n"
            "Вернуть убранные файлы».",
        )
        if answer == QMessageBox.Yes:
            self.db.remove_files(ids)
            self.refresh_all()

    def on_missing_menu(self, global_pos):
        menu = QMenu(self)
        act_check = menu.addAction("🔄 Проверить файлы сейчас")
        act_forget = menu.addAction("Убрать все потерянные из библиотеки…")
        chosen = menu.exec(global_pos)
        if chosen == act_check:
            self.check_files()
        elif chosen == act_forget:
            ids = self.db.missing_ids()
            answer = QMessageBox.question(
                self, "Убрать потерянные",
                f"Убрать из библиотеки все потерянные файлы ({len(ids)})?\n"
                "Их теги забудутся. Если это флешка, которую просто вынули, лучше подожди.",
            )
            if answer == QMessageBox.Yes:
                backup.make_backup(self.db.conn, "remove-missing")
                self.db.remove_files(ids)
                self.refresh_all()

    # ---------- поиск ----------
    def insert_search(self, text):
        current = self.search.text()
        sep = "" if not current or current.endswith(" ") or text.startswith(" ") else " "
        self.search.setText(current + sep + text)
        self.search.setFocus()

    def update_search_hint(self):
        groups = query.parse(self.search.text())
        show = bool(groups) and not query.is_simple(groups)
        self.search_hint.setVisible(show)
        if show:
            self.search_hint.setText("Ищу: " + query.describe(groups))

    # ---------- пустой экран ----------
    def update_empty_state(self, n_files):
        if n_files:
            self.views.setCurrentIndex(0 if self.mode == "grid" else 1)
            return
        welcome = self.db.count_files() == 0
        self.empty_btn2.setVisible(welcome)
        if welcome:
            # v1.7: первый экран - по шагам, что делать (раньше новичкам было непонятно, с чего начать)
            title, btn, action = "Добро пожаловать! Начни в три шага", "📂 Добавить папку", self.add_folder
            text = ("<table align='center' cellpadding='6'>"
                    "<tr><td style='font-size:18px'>1</td><td><b>Добавь папку</b> с файлами. Файлы останутся "
                    "на своих местах - программа их только запомнит.</td></tr>"
                    "<tr><td style='font-size:18px'>2</td><td><b>Поставь теги:</b> выдели файлы и нажми Ctrl+T "
                    "(например «Учёба», «Важное»).</td></tr>"
                    "<tr><td style='font-size:18px'>3</td><td><b>Находи за секунды:</b> пиши <b>#тег</b> "
                    "в поиске или кликай по тегам над файлами.</td></tr></table>")
        elif self.active_sub_filter():
            title, text = SUB_FILTER_EMPTY[self.active_sub_filter()]
            btn, action = "✕ Показать все файлы", lambda: self.set_sub_filter("")
        elif self.search.text().strip() or self.include or self.exclude:
            title, text, btn, action = (
                "Ничего не найдено",
                "Под такой поиск и фильтр тегов файлов нет.",
                "✕ Сбросить поиск и теги", self.reset_all_filters)
        else:
            empty_texts = {
                "fav": ("В избранном пусто", "Нажми ☆ у файла справа или перетащи файлы на «★ Избранное»."),
                "no_tags": ("Все файлы разобраны", "Здесь появятся файлы, к которым не подобрался ни один тег."),
                "no_user_tags": ("Все файлы с тегами", "У каждого файла есть хотя бы один твой тег. Отлично!"),
                "no_auto_tags": ("Все типы файлов знакомы", "Нет файлов неизвестного типа."),
                "missing": ("Потерянных нет", "Все файлы на своих местах."),
                "duplicates": ("Дубликатов нет", "Файлов с одинаковым содержимым не найдено."),
                "folder": ("В этой папке пока нет файлов",
                           "Возможно, они ещё добавляются - или всё лежит в служебных папках, которые пропускаются."),
                "recent": ("Пока ничего не открывали", "Открой файл двойным кликом или Enter - он появится здесь."),
                "static": ("Коллекция пустая", "Перетащи сюда файлы из сетки или отметь коллекцию справа."),
                "dynamic": ("Под правила пока ничего не подходит", "ПКМ по коллекции → «Изменить правила…»."),
            }
            title, text = empty_texts.get(self.view[0], ("Пусто", ""))
            btn, action = "", None
        self.empty_title.setText(title)
        self.empty_text.setText(text)
        self.empty_btn.setText(btn)
        self.empty_btn.setVisible(bool(btn))
        self.empty_action = action
        self.views.setCurrentIndex(2)

    def show_moved_notice(self, items, count):
        """Главное отличие программы - показываем его явно: файл нашёлся, теги на месте."""
        from html import escape  # noqa: PLC0415
        if count == 1 and items:
            old, new = items[0]
            what = (f"Файл <b>{escape(old)}</b> переименован в <b>{escape(new)}</b>" if old != new
                    else f"Файл <b>{escape(new)}</b> перемещён в другую папку")
        else:
            names = ", ".join(escape(n) for _o, n in items[:3]) + ("…" if count > 3 else "")
            what = f"Переименовано или перемещено файлов: <b>{count}</b> ({names})"
        self.notice_label.setText(f"🔄 {what} - программа нашла его сама. "
                                  "<b>Теги, коллекции и оценки сохранены.</b>")
        self.notice_bar.setVisible(True)
        self.notice_timer.start(20000)

    def update_tag_hint(self):
        show = (not self.settings["hint_tags_done"] and self.db.count_files() > 0
                and not self.db.has_user_tags())
        self.hint_bar.setVisible(show)

    def dismiss_tag_hint(self):
        self.settings.set("hint_tags_done", True)
        self.hint_bar.setVisible(False)

    def on_empty_action(self):
        if self.empty_action:
            self.empty_action()

    def reset_all_filters(self):
        self.include.clear()
        self.exclude.clear()
        self.search.clear()
        self.refresh_files()

    # ---------- «☰ Ещё» ----------
    def open_rules(self):
        dlg = AutoRulesDialog(self.db, self)
        dlg.exec()
        if dlg.changed:
            self.refresh_all()

    def open_folders_to_tags(self):
        dlg = FoldersToTagsDialog(self.db, self)
        if dlg.exec() == QDialog.Accepted and dlg.created:
            self.refresh_all()
            self.statusBar().showMessage(
                f"Из папок создано тегов-правил: {dlg.created}, поставлено тегов: {dlg.tagged}", 8000)

    def open_backups(self):
        dlg = BackupsDialog(self.db, self)
        dlg.exec()
        if dlg.restored:
            self.include.clear()
            self.exclude.clear()
            self.view = ("all", 0)
            self.cover_cache.clear()
            self.refresh_all()
            self.statusBar().showMessage("База восстановлена из резервной копии", 8000)
            self.check_files(manual=False)

    def export_tags(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт тегов", "теги виртуального проводника.json", "JSON (*.json)")
        if path:
            n = transfer.export_json(self.db, path)
            self.statusBar().showMessage(f"Выгружено файлов с тегами: {n} → {path}", 8000)

    def import_tags(self):
        path, _ = QFileDialog.getOpenFileName(self, "Импорт тегов", "", "JSON (*.json)")
        if not path:
            return
        backup.make_backup(self.db.conn, "import")
        try:
            report = transfer.import_json(self.db, path)
        except (ValueError, KeyError, OSError) as exc:
            QMessageBox.warning(self, "Импорт", f"Не получилось прочитать файл:\n{exc}")
            return
        self.refresh_all()
        QMessageBox.information(self, "Импорт", report.text())

    def open_data_dir(self):
        os.startfile(str(paths.data_dir()))  # только Windows

    def run_auto_tags(self):
        self.db.apply_auto_tags()
        self.refresh_all()
        self.statusBar().showMessage("Авто-теги проставлены по расширениям файлов")

    def new_collection(self):
        name, ok = QInputDialog.getText(self, "Новая коллекция", "Название:")
        if not ok or not name.strip():
            return
        cid = self.db.create_collection(name)
        if cid is None:
            QMessageBox.warning(self, "Ошибка", "Коллекция с таким именем уже есть.")
            return
        self.view = ("static", cid)
        self.refresh_all()

    def new_dynamic_collection(self):
        # как в Steam: текущий фильтр по тегам сразу подставляется в правила
        rules = {}
        if self.include:
            rules["tags"] = list(self.include)
            if self.tag_mode == "any":
                rules["tag_mode"] = "any"
        if self.exclude:
            rules["exclude_tags"] = list(self.exclude)
        if self.search.text().strip():
            rules["query"] = self.search.text().strip()
        dlg = DynamicCollectionDialog(self.db, self, rules=rules)
        if dlg.exec() != QDialog.Accepted:
            return
        name, rules = dlg.result_data()
        if not name:
            QMessageBox.warning(self, "Ошибка", "Нужно название.")
            return
        cid = self.db.create_collection(name, rules)
        if cid is None:
            QMessageBox.warning(self, "Ошибка", "Коллекция с таким именем уже есть.")
            return
        self.view = ("dynamic", cid)
        self.include.clear()
        self.exclude.clear()
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.refresh_all()

    # ================= отмена (Ctrl+Z / Ctrl+Y) =================
    def _undoable(self, func, label):
        """Обёртка: копия базы перед действием; если ничего не изменилось - копия выбрасывается."""
        import functools
        import inspect

        try:
            params = inspect.signature(func).parameters.values()
            has_var = any(p.kind == p.VAR_POSITIONAL for p in params)
            n_pos = sum(1 for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD))
        except (TypeError, ValueError):
            has_var, n_pos = True, 0

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not has_var:
                args = args[:n_pos]   # сигналы Qt передают лишнее (например, checked у кнопок)
            if self._undo_depth:      # вложенный вызов - шаг уже снят снаружи
                return func(*args, **kwargs)
            self.flush_note()
            before = self.db.conn.total_changes
            self.undo.checkpoint(label)
            self._undo_depth += 1
            try:
                return func(*args, **kwargs)
            finally:
                self._undo_depth -= 1
                if self.db.conn.total_changes == before:
                    self.undo.drop_last()
                self.update_undo_actions()

        return wrapper

    def update_undo_actions(self):
        if not hasattr(self, "undo_action"):
            return
        u, r = self.undo.undo_label(), self.undo.redo_label()
        self.undo_action.setEnabled(bool(u))
        self.redo_action.setEnabled(bool(r))
        self.undo_action.setToolTip(f"Отменить: {u}  (Ctrl+Z)" if u else "Нечего отменять")
        self.redo_action.setToolTip(f"Повторить: {r}  (Ctrl+Y)" if r else "Нечего повторять")

    def do_undo(self):
        self._apply_history(self.undo.undo, "Отменено")

    def do_redo(self):
        self._apply_history(self.undo.redo, "Повторено")

    def _apply_history(self, step, word):
        self.flush_note()
        self._note_checkpointed = None
        try:
            label = step()
        except OSError as exc:
            QMessageBox.warning(self, "Отмена", f"Не получилось вернуть файлы на диске:\n{exc}")
            self.update_undo_actions()
            return
        if label is None:
            self.statusBar().showMessage("Нечего " + ("отменять" if word == "Отменено" else "повторять"), 3000)
            return
        self.cover_cache.clear()
        self.refresh_all()
        self.update_undo_actions()
        self.statusBar().showMessage(f"{word}: {label}", 5000)
        self.check_files(manual=False)   # сверить с диском: копия базы могла быть старше

    # ================= горячие клавиши =================
    # (id, клавиши по умолчанию, метод, описание, только в списке файлов)
    # Свои клавиши хранятся в настройках: settings["shortcuts"][id]
    SHORTCUTS = [
        ("quick_view", "Space", "open_quick_view", "Быстрый просмотр выделенного файла", True),
        ("open", "Return", "open_selected", "Открыть файл", True),
        ("reveal", "Ctrl+E", "reveal_selected", "Показать файл в Проводнике", True),
        ("rename", "F2", "rename_selected", "Переименовать (несколько файлов - по шаблону)", True),
        ("remove", "Delete", "remove_selected_from_library", "Убрать из библиотеки (с диска - нет)", True),
        ("favorite", "Ctrl+D", "toggle_selected_favorite", "В избранное / из избранного", True),
        ("rate1", "1", "rate_1", "Оценка ★", True),
        ("rate2", "2", "rate_2", "Оценка ★★", True),
        ("rate3", "3", "rate_3", "Оценка ★★★", True),
        ("rate4", "4", "rate_4", "Оценка ★★★★", True),
        ("rate5", "5", "rate_5", "Оценка ★★★★★", True),
        ("rate0", "0", "rate_0", "Снять оценку", True),
        ("tags", "Ctrl+T", "open_tag_editor", "Окно меток для выделенных файлов", False),
        ("undo", "Ctrl+Z", "do_undo", "Отменить последнее действие", False),
        ("redo", "Ctrl+Y", "do_redo", "Повторить отменённое", False),
        ("redo2", "Ctrl+Shift+Z", "do_redo", "Повторить отменённое (второе сочетание)", False),
        ("search", "Ctrl+F", "focus_search", "Перейти в строку поиска", False),
        ("reset", "Escape", "reset_all_filters", "Сбросить поиск и фильтр тегов", False),
        ("check", "F5", "check_files", "Проверить файлы на диске", False),
        ("grid", "Ctrl+1", "grid_mode", "Сетка обложек", False),
        ("list", "Ctrl+2", "list_mode", "Список (таблица)", False),
        ("stats", "Ctrl+I", "open_stats", "Статистика библиотеки", False),
        ("back", "Alt+Left", "go_back", "Назад (к предыдущему разделу)", False),
        ("forward", "Alt+Right", "go_forward", "Вперёд", False),
        ("details", "Ctrl+P", "toggle_details_key", "Показать/спрятать панель деталей", False),
        ("settings", "Ctrl+,", "open_settings", "Настройки", False),
        ("guide", "F1", "open_help", "Инструкция и обучение (в настройках)", False),
    ]

    def shortcut_keys(self):
        """{id: клавиши} с учётом своих настроек."""
        custom = self.settings["shortcuts"] or {}
        return {sid: custom.get(sid, default) for sid, default, *_ in self.SHORTCUTS}

    def setup_shortcuts(self):
        for act, target in getattr(self, "_shortcut_actions", []):
            target.removeAction(act)
            act.deleteLater()
        self._shortcut_actions = []
        keys = self.shortcut_keys()
        for sid, _default, method, _desc, views_only in self.SHORTCUTS:
            if not keys[sid]:
                continue
            slot = getattr(self, method)
            targets = (self.grid, self.table) if views_only else (self,)
            for target in targets:
                act = QAction(target)
                act.setShortcut(QKeySequence(keys[sid]))
                # клавиши без Ctrl (пробел, цифры, Delete) работают только в списке файлов,
                # чтобы не мешать печатать в поиске и заметке
                act.setShortcutContext(Qt.WidgetWithChildrenShortcut if views_only else Qt.WindowShortcut)
                act.triggered.connect(lambda _=False, f=slot: f())
                target.addAction(act)
                self._shortcut_actions.append((act, target))

    def shortcut_defs(self):
        return [(sid, default, desc) for sid, default, _m, desc, _v in self.SHORTCUTS]

    def shortcut_rows(self):
        keys = self.shortcut_keys()
        rows = [(keys[sid], desc) for sid, _d, _m, desc, _v in self.SHORTCUTS if keys[sid]]
        rows.append(("Ctrl+A", "Выделить все файлы"))
        rows.append(("Ctrl / Shift + клик", "Выделить несколько файлов"))
        rows.append(("#  в поиске", "Автодополнение тегов"))
        return rows

    def open_shortcuts(self):
        self.open_settings(page=2)

    def focus_search(self):
        self.search.setFocus()
        self.search.selectAll()

    def grid_mode(self):
        self.set_mode("grid")

    def list_mode(self):
        self.set_mode("list")

    def open_selected(self):
        f = self.db.get_file(self.current_file_id()) if self.current_file_id() is not None else None
        if f is not None:
            self.open_path(f["path"])

    def reveal_selected(self):
        f = self.db.get_file(self.current_file_id()) if self.current_file_id() is not None else None
        if f is not None:
            self.reveal(f["path"])

    def toggle_selected_favorite(self):
        ids = self.selected_file_ids()
        if ids:
            files = self.db.get_files(ids)
            self.toggle_favorite(ids, not all(f["favorite"] for f in files))

    def rate_0(self):
        self.rate_files(self.selected_file_ids(), 0)

    def rate_1(self):
        self.rate_files(self.selected_file_ids(), 1)

    def rate_2(self):
        self.rate_files(self.selected_file_ids(), 2)

    def rate_3(self):
        self.rate_files(self.selected_file_ids(), 3)

    def rate_4(self):
        self.rate_files(self.selected_file_ids(), 4)

    def rate_5(self):
        self.rate_files(self.selected_file_ids(), 5)

    # ================= оценка =================
    def rate_files(self, file_ids, value):
        ids = list(file_ids)
        if not ids:
            return
        self.db.set_rating(ids, value)
        self.refresh_files()
        n = len(ids)
        self.statusBar().showMessage(
            (f"Оценка {stars_text(value)}" if value else "Оценка снята") + (f" - файлов: {n}" if n > 1 else ""), 3000)

    # ================= быстрый просмотр =================
    def visible_file_ids(self):
        if self.mode == "grid":
            return [self.grid.item(i).data(Qt.UserRole) for i in range(self.grid.count())]
        return [self.table.item(r, COL_NAME).data(Qt.UserRole) for r in range(self.table.rowCount())]

    def open_quick_view(self):
        current = self.current_file_id()
        if current is None:
            return
        ids = self.visible_file_ids()
        index = ids.index(current) if current in ids else 0
        dlg = QuickView(self.db, ids, index,
                        on_rate=lambda fid, v: self.rate_files([fid], v),
                        on_open=self.open_path, parent=self)
        dlg.exec()
        # вернуть выделение на файл, на котором закончили просмотр
        last = ids[dlg.index] if ids else current
        self.reload([last])

    # ================= заметка =================
    def load_note(self, f, multi=False):
        self.note_timer.stop()
        self.note_edit.blockSignals(True)
        self._note_file = f["id"] if f is not None else None
        self.note_edit.setPlainText(f["note"] if f is not None else "")
        self.note_edit.setEnabled(f is not None)
        self.note_edit.setPlaceholderText(
            "Заметка есть у каждого файла отдельно - выдели один файл" if multi
            else "Заметка к файлу… (ищется поиском: заметка:текст)")
        self.note_edit.blockSignals(False)

    def save_note(self):
        fid = self._note_file
        if fid is None:
            return
        f = self.db.get_file(fid)
        text = self.note_edit.toPlainText()
        if f is None or (f["note"] or "") == text:
            return
        if self._note_checkpointed != fid:   # одна точка отмены на одно редактирование заметки
            self.undo.checkpoint("заметка")
            self._note_checkpointed = fid
            self.update_undo_actions()
        self.db.set_note(fid, text)

    def flush_note(self):
        if hasattr(self, "note_timer") and self.note_timer.isActive():
            self.note_timer.stop()
            self.save_note()

    # ================= поиск: автодополнение и история =================
    def on_search_edited(self, text):
        token = text.split(" ")[-1] if text else ""
        bare = token[1:] if token.startswith("-") else token
        if not bare.startswith("#"):
            self.tag_completer.popup().hide()
            return
        names = []
        for t in self.db.get_tags_with_counts():
            name = t["name"]
            names.append("#" + (f'"{name}"' if " " in name else name))
        self.tag_completer_model.setStringList(names)
        self.tag_completer.setCompletionPrefix(bare)
        if self.tag_completer.completionCount():
            self.tag_completer.complete()
        else:
            self.tag_completer.popup().hide()

    def insert_completion(self, completion):
        text = self.search.text()
        head, _sep, token = text.rpartition(" ")
        minus = "-" if token.startswith("-") else ""
        self.search.setText((head + " " if head else "") + minus + completion + " ")
        self.search.setFocus()

    def remember_search(self):
        text = self.search.text().strip()
        if len(text) >= 2 and self.views.currentIndex() != 2:   # что-то нашлось
            self.db.push_search_history(text)

    def fill_help_menu(self):
        menu = self.help_menu
        menu.clear()
        history = self.db.get_setting("search_history", [])
        if history:
            menu.addSection("Недавние поиски")
            for h in history[:10]:
                menu.addAction("🕘 " + h).triggered.connect(lambda _=False, q=h: self.search.setText(q))
            menu.addAction("Очистить историю").triggered.connect(
                lambda: self.db.set_setting("search_history", []))
        menu.addSection("Подсказки - нажми, чтобы вставить")
        for example, label in self._help_examples:
            menu.addAction(label).triggered.connect(lambda _=False, e=example: self.insert_search(e))

    # ================= цвета картинок =================
    def scan_colors(self):
        if self._colors_running or not self.settings["auto_colors"]:
            return
        rows = [(r["id"], r["path"]) for r in self.db.images_without_colors(sorted(IMAGE_EXTS))]
        if not rows:
            return
        self._colors_running = True
        self.background.run(compute_colors, (rows,), self.on_colors_scanned)

    def on_colors_scanned(self, result):
        self._colors_running = False
        if isinstance(result, Exception) or not result:
            return
        self.db.set_colors(result)
        if len(result) >= 400:      # обрабатываем порциями - следующая порция
            QTimer.singleShot(0, self.scan_colors)

    # ================= статистика =================
    def open_stats(self):
        StatsDialog(self.db.stats(), self).exec()

    # ================= пакетное переименование =================
    def rename_selected(self):
        ids = self.selected_file_ids()
        files = [f for f in self.db.get_files(ids) if f["missing_since"] is None]
        if not files:
            return
        order = {fid: i for i, fid in enumerate(ids)}
        files.sort(key=lambda f: order[f["id"]])
        first_tags = {}
        for f in files:
            own = [t for t in self.db.get_file_tags(f["id"]) if not t["is_auto"]]
            if own:
                first_tags[f["id"]] = own[0]["name"]
        dlg = RenameDialog(files, first_tags, self)
        if dlg.exec() != QDialog.Accepted:
            return
        plan = dlg.plan
        try:
            done = rename.apply_plan(plan)
        except OSError as exc:
            QMessageBox.warning(self, "Переименование", f"Не получилось, ничего не изменено:\n{exc}")
            return
        for fid, _old, new in done:
            self.db.relink(fid, new)
        # отмена вернёт и имена на диске, и записи в базе
        self.undo.set_fs(lambda d=done: rename.revert(d),
                         lambda d=done: rename.apply_plan([rename.Item(*x) for x in d]))
        self.cover_cache.clear()
        self.reload([fid for fid, _o, _n in done])
        self.statusBar().showMessage(f"Переименовано файлов: {len(done)}. Отменить - Ctrl+Z", 6000)


    # ================= добавление папки (в фоне, с защитой) =================
    def start_add_folder(self, folder):
        if self.adder.busy:
            QMessageBox.information(self, "Добавление папки", "Сейчас уже добавляется другая папка - дождись конца.")
            return
        folder = os.path.abspath(folder)
        level, msg = safety.check_folder(folder, paths.data_dir())
        if level == "block":
            QMessageBox.warning(self, "Эту папку добавить нельзя", msg)
            return
        if level == "warn" and QMessageBox.question(self, "Очень большая папка", msg) != QMessageBox.Yes:
            return
        self.db.add_watched_folder(folder)
        self._adding = {"folder": folder, "added": 0, "watch_was": self.watcher.enabled}
        self.watcher.enabled = False   # пока идёт добавление, слежение не дёргаем
        dlg = QProgressDialog("Ищу файлы…", "Остановить", 0, 0, self)
        dlg.setWindowTitle(f"Добавление: {os.path.basename(folder) or folder}")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(300)
        dlg.setMinimumWidth(460)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.canceled.connect(self.adder.cancel)
        self._adding["dialog"] = dlg
        self.adder.start(folder)
        dlg.show()

    def on_add_batch(self, batch):
        if self._adding is None:
            return
        self._adding["added"] += self.db.add_files_bulk(batch)

    def on_add_progress(self, found, current_dir):
        if self._adding is None:
            return
        shown = current_dir if len(current_dir) < 70 else "…" + current_dir[-68:]
        self._adding["dialog"].setLabelText(
            f"Найдено файлов: {found:,}   ·   добавлено новых: {self._adding['added']:,}\n{shown}".replace(",", " "))

    def on_add_big(self, found):
        answer = QMessageBox.question(
            self, "В папке очень много файлов",
            f"Найдено уже {found:,} файлов, и это ещё не всё.\n\n".replace(",", " ")
            + "Такая библиотека будет работать медленнее. Может, это не та папка? "
              "Продолжить добавление?")
        self.adder.answer_big(answer == QMessageBox.Yes)

    def on_add_finished(self, cancelled, found):
        info = self._adding or {}
        self._adding = None
        self.adder.busy = False
        dlg = info.get("dialog")
        if dlg is not None:
            dlg.close()
        folder, added = info.get("folder"), info.get("added", 0)
        self.watcher.enabled = info.get("watch_was", True)
        if cancelled and folder:
            box = QMessageBox(self)
            box.setWindowTitle("Добавление остановлено")
            box.setText(f"Остановлено. Уже добавлено файлов: {added}.")
            box.setInformativeText("Оставить их в библиотеке? За папкой следить не буду, чтобы она "
                                   "не продолжила добавляться сама.")
            keep = box.addButton("Оставить добавленное", QMessageBox.AcceptRole)
            box.addButton("Убрать всё", QMessageBox.DestructiveRole)
            box.exec()
            self.db.remove_watched_folder(folder, remove_files=box.clickedButton() is not keep)
            self.refresh_all()
            return
        self.refresh_all()
        self.statusBar().showMessage(f"Добавлено новых файлов: {added}. Теперь слежу за этой папкой.", 8000)
        if self.watcher.enabled:
            self.watcher.check_all(manual=False)  # подхватить папку в слежение

    # ================= папки в сайдбаре =================
    def on_folder_menu(self, folder_id, global_pos):
        path = self.db.get_folder_path(folder_id)
        if path is None:
            return
        menu = QMenu(self)
        act_show = menu.addAction("Показать в Проводнике")
        act_check = menu.addAction("🔄 Проверить файлы")
        menu.addSeparator()
        act_remove = menu.addAction("Убрать папку из библиотеки…")
        chosen = menu.exec(global_pos)
        if chosen == act_show:
            if os.path.isdir(path):
                os.startfile(path)  # только Windows
            else:
                self.statusBar().showMessage("Папки нет на диске - диск отключён или папку удалили", 6000)
        elif chosen == act_check:
            self.check_files()
        elif chosen == act_remove:
            self.remove_library_folder(path)

    def remove_library_folder(self, path):
        box = QMessageBox(self)
        box.setWindowTitle("Убрать папку")
        box.setText(f"Перестать следить за папкой?\n{path}")
        box.setInformativeText("С диска ничего не удаляется. Что сделать с её файлами в библиотеке?")
        keep = box.addButton("Оставить в библиотеке", QMessageBox.AcceptRole)
        drop = box.addButton("Убрать из библиотеки", QMessageBox.DestructiveRole)
        box.addButton("Отмена", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() not in (keep, drop):
            return
        if box.clickedButton() is drop:
            backup.make_backup(self.db.conn, "remove-folder")
        removed = self.db.remove_watched_folder(path, remove_files=box.clickedButton() is drop)
        if self.view[0] == "folder":
            self.view = ("all", 0)
        self.refresh_all()
        self.statusBar().showMessage(
            "Папка убрана из библиотеки" + (f", файлов убрано: {removed}" if removed else ""), 6000)

    def startup_checks(self):
        bad = [p for p in self.db.get_folders() if safety.check_folder(p, paths.data_dir())[0] == "block"
               and os.path.isdir(p)]
        if bad:
            listing = "\n".join("• " + p for p in bad)
            answer = QMessageBox.question(
                self, "В библиотеке слишком большие папки",
                f"Эти папки - весь системный диск или системные папки:\n{listing}\n\n"
                "Из-за них программа может зависать. Убрать их из библиотеки вместе с их файлами? "
                "С диска ничего не удаляется, перед этим сохранится резервная копия базы.")
            if answer == QMessageBox.Yes:
                backup.make_backup(self.db.conn, "remove-folder")
                for p in bad:
                    self.db.remove_watched_folder(p, remove_files=True)
                self.refresh_all()
        self.watcher.enabled = bool(self.settings["watch_folders"])
        if self.watcher.enabled:
            self.watcher.check_all(manual=False)
        QTimer.singleShot(4000, self.auto_check_updates)

    # ================= обновления (GitHub Releases) =================
    def auto_check_updates(self):
        """Раз в день, в фоне, если включено в настройках и программа собрана на GitHub."""
        if not GITHUB_REPO or not self.settings["check_updates"]:
            return
        if time.time() - float(self.settings["update_checked"] or 0) < 24 * 3600:
            return
        self.check_updates(manual=False)

    def check_updates(self, manual=True):
        if not GITHUB_REPO:
            if manual:
                QMessageBox.information(self, "Обновления", "Эта копия собрана не на GitHub - проверять негде.")
            return
        if self._update_running:
            return
        self._update_running = True
        if manual:
            self.statusBar().showMessage("Проверяю обновления…")
        self.net.run(updates.fetch_latest, (GITHUB_REPO,), lambda rel: self.on_update_result(rel, manual))

    def on_update_result(self, rel, manual=False):
        self._update_running = False
        if isinstance(rel, Exception):
            rel = None
        if rel is None:
            if manual:
                QMessageBox.information(self, "Обновления", "Не получилось узнать о новой версии: нет интернета "
                                        "или на GitHub ещё нет ни одного релиза.")
            return
        self.settings.set("update_checked", int(time.time()))
        if not updates.is_newer(rel["version"]):
            if manual:
                QMessageBox.information(self, "Обновления", f"У тебя последняя версия - {VERSION}. 👍")
            return
        if not manual and rel["version"] == self.settings["skip_version"]:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("Есть обновление")
        box.setText(f"Вышла новая версия: {rel['version']} (у тебя {VERSION}).")
        notes = rel["notes"][:700] + ("…" if len(rel["notes"]) > 700 else "")
        box.setInformativeText((notes + "\n\n" if notes else "") +
                               "Скачай установщик и запусти его - теги, коллекции и настройки сохранятся.")
        download = box.addButton("⬇ Скачать", QMessageBox.AcceptRole)
        skip = box.addButton("Пропустить эту версию", QMessageBox.RejectRole)
        box.addButton("Позже", QMessageBox.RejectRole)
        box.setDefaultButton(download)
        box.exec()
        if box.clickedButton() is download:
            QDesktopServices.openUrl(QUrl(rel["installer"] or rel["url"]))
        elif box.clickedButton() is skip:
            self.settings.set("skip_version", rel["version"])

    def open_error_log(self):
        path = crashlog.log_path()
        if not path.exists():
            path.write_text("Ошибок пока не было.\n", encoding="utf-8")
        os.startfile(str(path))  # только Windows

    # ================= безопасный режим =================
    def show_safe_mode_help(self):
        QMessageBox.information(
            self, "Безопасный режим",
            "Программа не проверяет файлы на диске и не следит за папками.\n\n"
            "Сейчас откроются «Папки библиотеки»: убери папку, из-за которой всё зависало "
            "(например, весь диск). Когда закончишь - нажми «🔄 Проверить файлы», "
            "и программа заработает как обычно.")
        self.open_library_folders()

    # ================= порции, история, тема =================
    def show_more(self):
        self.page_limit += self.page_size()
        self.reload(self.selected_file_ids())

    def push_history(self):
        if self._history and self._history[self._history_pos] == self.view:
            return
        self._history = self._history[:self._history_pos + 1] + [self.view]
        self._history = self._history[-50:]
        self._history_pos = len(self._history) - 1
        self.update_nav_actions()

    def update_nav_actions(self):
        if hasattr(self, "back_action"):
            self.back_action.setEnabled(self._history_pos > 0)
            self.fwd_action.setEnabled(self._history_pos < len(self._history) - 1)

    def _go(self, delta):
        pos = self._history_pos + delta
        if not 0 <= pos < len(self._history):
            return
        self._history_pos = pos
        self.view = self._history[pos]
        self.refresh_all()
        self.update_nav_actions()

    def go_back(self):
        self._go(-1)

    def go_forward(self):
        self._go(1)

    # ================= настройки =================
    def page_size(self):
        return int(self.settings["page_size"])

    def open_settings(self, page=0):
        dlg = SettingsDialog(
            self.settings, self.shortcut_defs(), self, page=page, on_guide=self.open_guide,
            on_tour=lambda: QTimer.singleShot(200, self.start_tour),
            on_data_dir=self.open_data_dir, data_dir=str(paths.data_dir()),
            on_check_updates=lambda: self.check_updates(manual=True), on_open_log=self.open_error_log)
        dlg.on_apply = self.apply_settings
        dlg.exec()
        if dlg.changed_keys:
            self.apply_settings(dlg.changed_keys)

    def apply_settings(self, changed=None):
        """Применить настройки сразу - без перезапуска (кроме масштаба интерфейса)."""
        s = self.settings
        if changed and "ui_scale" in changed:
            QTimer.singleShot(0, self.ask_restart_for_scale)
        changed = set(changed or s.data)
        if changed & {"theme", "custom_colors", "custom_themes", "font_family", "font_pt", "text_color", "density"}:
            apply_theme(QApplication.instance(), s)
        if "shortcuts" in changed:
            self.setup_shortcuts()
        if "show_details" in changed:
            self.right.setVisible(bool(s["show_details"]))
            self.details_action.blockSignals(True)
            self.details_action.setChecked(bool(s["show_details"]))
            self.details_action.blockSignals(False)
        if "big_folder_files" in changed:
            safety.BIG_FOLDER_FILES = int(s["big_folder_files"])
        if "watch_folders" in changed and not self.safe_mode:
            self.watcher.enabled = bool(s["watch_folders"])
        if "page_size" in changed:
            self.page_limit = self.page_size()
        self.cover_cache.clear()
        self.refresh_all()

    def ask_restart_for_scale(self):
        answer = QMessageBox.question(
            self, "Масштаб интерфейса",
            f"Масштаб {self.settings['ui_scale']}% применится после перезапуска. Перезапустить сейчас?")
        if answer == QMessageBox.Yes:
            self.restart_requested = True   # main.py запустит программу снова после закрытия окна
            self.close()

    def set_theme(self, key, menu=None):
        self.settings.set("theme", key)
        self.apply_settings({"theme"})

    def toggle_details(self, on):
        self.right.setVisible(on)
        if bool(self.settings["show_details"]) != on:
            self.settings.set("show_details", on)

    def toggle_details_key(self):
        self.details_action.toggle()

    def open_guide(self):
        """Текстовая инструкция (открывается из настроек)."""
        GuideDialog(self).exec()

    def open_help(self):
        self.open_settings(page=SettingsDialog.PAGE_GUIDE)

    # ================= обучение со стрелками =================
    def tour_steps(self):
        tb = self.toolbar
        return [
            (None, "👋 Привет!", "Покажу, где что находится - это займёт минуту.<br>"
             "<b>Enter</b> или «Далее» - следующий шаг, <b>Esc</b> - закрыть."),
            (lambda: self.add_btn, "＋ Добавить", "Начни отсюда: <b>Добавить → Папку</b>. Файлы останутся на своих "
             "местах - программа их запомнит и будет следить за папкой. Здесь же - новые коллекции."),
            (lambda: self.sidebar, "Библиотека", "Разделы, коллекции и папки. <b>Перетаскивай файлы</b> на коллекцию. "
             "ПКМ по «Все файлы» - показать только файлы <b>без тегов</b>."),
            (lambda: self.search, "Умный поиск", "Пиши имя или <b>#тег</b>, <b>-#тег</b>, <b>.pdf</b>, "
             "<b>размер&gt;10мб</b>, <b>оценка&gt;=4</b>… Кнопка <b>?</b> рядом - подсказки и история."),
            (lambda: self.mode_box, "Фильтр по тегам", "Плашки тегов появятся под этой строкой. Клик по плашке - "
             "<b>✓ нужен</b>, ещё клик - <b>✕ исключить</b>. Здесь же - «все теги» или «любой»."),
            (lambda: self.views, "Твои файлы", "<b>Пробел</b> - быстрый просмотр, <b>Enter</b> - открыть, "
             "<b>F2</b> - переименовать. Ctrl/Shift + клик - выделить несколько."),
            (lambda: self.view_btn, "Сетка или список", "Переключает вид одной кнопкой. Ползунок рядом - "
             "размер обложек (только в сетке)."),
            (lambda: self.right, "Детали файла", "★ избранное, <b>оценка</b> (клавиши 1-5), теги, <b>заметка</b> "
             "и коллекции выделенного файла. Спрятать панель - кнопка ▤ или Ctrl+P."),
            (lambda: tb.widgetForAction(self.undo_action), "Отмена", "<b>↶ ↷</b> - отменить и повторить любое "
             "действие (Ctrl+Z / Ctrl+Y). Ничего не потеряется."),
            (lambda: self.menu_btn, "☰ Ещё", "Правила авто-тегов, дубликаты, статистика, резервные копии, "
             "экспорт и импорт."),
            (lambda: tb.widgetForAction(self.settings_action), "⚙ Настройки", "Темы и свои цвета, шрифт, "
             "горячие клавиши. Там же можно снова пройти это обучение. Удачи! 🎉"),
        ]

    def start_tour(self):
        old = getattr(self, "_tour", None)
        if old is not None:
            try:
                old.finish()
            except RuntimeError:
                pass
        accent = "#66c0f4"
        try:
            from app.ui.theme import colors_for  # noqa: PLC0415
            accent = (colors_for(self.settings["theme"], self.settings) or {}).get("accent", accent)
        except Exception:  # noqa: BLE001
            pass
        self._tour = Tour(self, self.tour_steps(), accent)
        self._tour.finished.connect(self.on_tour_finished)
        self._tour.start()

    def on_tour_finished(self):
        self._tour = None
        if not self.settings["onboarding_done"]:
            self.settings.set("onboarding_done", True)

    # ================= фильтр «без тегов» (ПКМ по Все/Избранное/Недавние) =================
    def active_sub_filter(self):
        return self.sub_filter if self.view[0] in ("all", "fav", "recent") else ""

    def set_sub_filter(self, value):
        self.sub_filter = value or ""
        self.update_sub_indicator()
        self.refresh_files()

    def update_sub_indicator(self):
        active = self.active_sub_filter()
        self.sub_btn.setVisible(bool(active))
        if active:
            self.sub_btn.setText(f"Показаны: {SUB_FILTERS[active].lower()}  ✕")

    def on_library_menu(self, kind, global_pos):
        menu = QMenu(self)
        menu.addSection("Показывать")
        group = []
        for key, label in [("", "Все файлы раздела"), *SUB_FILTERS.items()]:
            act = menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(self.sub_filter == key)
            if key:
                act.setToolTip(SUB_FILTER_HINTS[key])
            group.append((act, key))
        clear = None
        if kind == "recent":
            menu.addSeparator()
            clear = menu.addAction("Очистить «Недавние»")
        chosen = menu.exec(global_pos)
        if chosen is None:
            return
        if chosen is clear:
            self.db.clear_recent()
            self.refresh_all()
            return
        for act, key in group:
            if chosen is act:
                if self.view[0] != kind:
                    self.view = (kind, 0)
                    self.push_history()
                    self.refresh_sidebar()
                self.set_sub_filter(key)
                return


    # ================= запоминание окна =================
    def save_window_state(self):
        try:
            geo = bytes(self.saveGeometry().toBase64()).decode("ascii")
        except Exception:  # noqa: BLE001 - не мешаем закрытию окна
            geo = ""
        self.settings.set("window", {
            "geometry": geo, "splitter": [int(x) for x in self.splitter.sizes()], "mode": self.mode,
            "sort": self.sort_key, "cover": int(self.size_slider.value()),
            "view": list(self.view), "tag_mode": self.tag_mode, "sub_filter": self.sub_filter,
        })

    def restore_window_state(self):
        st = self.settings["window"] or {}
        if st.get("geometry"):
            try:
                self.restoreGeometry(QByteArray.fromBase64(st["geometry"].encode("ascii")))
            except Exception:  # noqa: BLE001
                pass
        if st.get("splitter") and len(st["splitter"]) == 3:
            self.splitter.setSizes([int(x) for x in st["splitter"]])
        if st.get("cover"):
            self.size_slider.setValue(int(st["cover"]))
        if st.get("sort"):
            idx = self.sort_box.findData(st["sort"])
            if idx >= 0:
                self.sort_box.setCurrentIndex(idx)
                self.sort_key = st["sort"]
        if st.get("mode") in ("grid", "list"):
            self.mode = st["mode"]
            self.views.setCurrentIndex(0 if self.mode == "grid" else 1)
        if self.settings["start_view"] == "last" and st.get("view"):
            self.view = (st["view"][0], st["view"][1])
            if self.view[0] in SUB_FILTERS:      # до v1.3 «без тегов» были отдельными разделами
                self.sub_filter, self.view = self.view[0], ("all", 0)
            self.sub_filter = st.get("sub_filter", self.sub_filter) or ""
            self._history = [self.view]
        self.update_view_toggle(self.mode)
        show = bool(self.settings["show_details"])
        self.right.setVisible(show)
        self.details_action.blockSignals(True)
        self.details_action.setChecked(show)
        self.details_action.blockSignals(False)
        self.setup_shortcuts()

    def closeEvent(self, event):
        self.save_window_state()
        self.flush_note()
        self.adder.shutdown()
        self.background.shutdown()
        self.net.shutdown()
        self.watcher.shutdown()
        self.thumbs.shutdown()
        super().closeEvent(event)
