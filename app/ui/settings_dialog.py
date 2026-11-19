"""Окно «⚙ Настройки».

Разворачивается на весь экран, каждая страница прокручивается. Настройки разложены
по карточкам: название и пояснение слева, переключатель справа. Внешний вид меняется
сразу (предпросмотр); «Отмена» возвращает как было, «Применить» / «ОК» - сохраняют.
"""
import copy

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFontComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.settings import DEFAULTS, DENSITY, LANGUAGES
from app.ui import theme as th
from app.version import GITHUB_REPO, VERSION

CONTROL_WIDTH = 260


def _muted(text):
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setObjectName("muted")   # цвет «второстепенного текста» из темы
    return lab


class Card:
    """Карточка с заголовком и строками «название + пояснение … переключатель»."""

    def __init__(self, page_layout, title):
        page_layout.addWidget(self._title(title))
        self.frame = QFrame()
        self.frame.setObjectName("card")
        self.layout = QVBoxLayout(self.frame)
        self.layout.setContentsMargins(16, 6, 16, 6)
        self.layout.setSpacing(0)
        page_layout.addWidget(self.frame)
        self.rows = 0

    @staticmethod
    def _title(text):
        lab = QLabel(text.upper())
        lab.setObjectName("cardTitle")
        lab.setContentsMargins(4, 14, 0, 4)
        return lab

    def row(self, title, desc, widget):
        if self.rows:
            line = QFrame()
            line.setObjectName("rowLine")
            line.setFrameShape(QFrame.HLine)
            self.layout.addWidget(line)
        self.rows += 1
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 10, 0, 10)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        t = QLabel(title)
        t.setObjectName("rowTitle")
        texts.addWidget(t)
        if desc:
            texts.addWidget(_muted(desc))
        h.addLayout(texts, 1)
        if widget is not None:
            if not isinstance(widget, QCheckBox):
                widget.setMinimumWidth(CONTROL_WIDTH)
            h.addWidget(widget, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.layout.addWidget(w)
        return w

    def widget(self, widget):
        self.layout.addWidget(widget)


def _combo(items, current):
    box = QComboBox()
    for key, label in items:
        box.addItem(label, key)
    idx = box.findData(current)
    box.setCurrentIndex(idx if idx >= 0 else 0)
    return box


def _check(value):
    cb = QCheckBox()
    cb.setChecked(bool(value))
    return cb


class _PageBody(QWidget):
    """Содержимое страницы. Подписи с переносом строк меняют высоту от ширины, а QScrollArea
    этого не учитывает: при первом показе строки налезали друг на друга. Поэтому при каждом
    изменении ширины сами задаём нужную высоту."""

    def _fit_height(self):
        lay = self.layout()
        if lay is None or not self.width():
            return
        lay.activate()
        need = lay.totalHeightForWidth(self.width()) if lay.hasHeightForWidth() else lay.totalMinimumSize().height()
        if need > 0 and need != self.minimumHeight():
            self.setMinimumHeight(need)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_height()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._fit_height)


def _page(title, subtitle):
    """Страница с прокруткой. -> (виджет для стека, layout для карточек)."""
    inner = _PageBody()
    lay = QVBoxLayout(inner)
    lay.setContentsMargins(28, 20, 28, 24)
    lay.setSpacing(4)
    head = QLabel(title)
    head.setObjectName("panelTitle")
    lay.addWidget(head)
    if subtitle:
        lay.addWidget(_muted(subtitle))
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setWidget(inner)
    return scroll, lay


class SettingsDialog(QDialog):
    """shortcut_defs: [(id, клавиши по умолчанию, описание)]. После exec() смотри changed_keys."""

    PAGES = ["🎨   Внешний вид", "📚   Библиотека", "⌨   Горячие клавиши", "❓   Инструкция", "ℹ   О программе"]
    PAGE_GUIDE = 3

    def __init__(self, settings, shortcut_defs, parent=None, page=0, on_guide=None, on_tour=None,
                 on_data_dir=None, data_dir="", on_check_updates=None, on_open_log=None):
        super().__init__(parent)
        self.settings = settings
        self.work = copy.deepcopy(settings.data)       # правим копию, сохраняем по «Применить»/«ОК»
        self.shortcut_defs = shortcut_defs
        self.on_guide, self.on_tour, self.on_data_dir = on_guide, on_tour, on_data_dir
        self.on_check_updates, self.on_open_log = on_check_updates, on_open_log
        self.on_apply = None
        self.changed_keys = set()
        self.setWindowTitle("Настройки")
        self.setWindowFlags(Qt.Window | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        self.setSizeGripEnabled(True)
        self.setMinimumSize(720, 480)
        self.resize(1040, 720)

        self.nav = QListWidget()
        self.nav.setObjectName("settingsNav")
        self.nav.addItems(self.PAGES)
        self.nav.setFixedWidth(230)
        self.pages = QStackedWidget()
        for build in (self._page_look, self._page_library, self._page_keys, self._page_guide):
            self.pages.addWidget(build())
        self.pages.addWidget(self._page_about(data_dir))
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(page)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Apply | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Apply).setText("Применить")
        buttons.button(QDialogButtonBox.Cancel).setText("Отмена")
        buttons.accepted.connect(self.on_ok)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self.apply)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(16, 8, 16, 12)
        bottom.addStretch(1)
        bottom.addWidget(buttons)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.addWidget(self.pages, 1)
        right.addLayout(bottom)
        body = QHBoxLayout(self)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.nav)
        body.addLayout(right, 1)

    # ================= Внешний вид =================
    def _page_look(self):
        page, lay = _page("Внешний вид", "Изменения видны сразу. «Отмена» вернёт как было.")
        w = self.work

        card = Card(lay, "Тема")
        self.theme = QComboBox()
        self.fill_theme_combo()
        self.theme.currentIndexChanged.connect(self.on_theme_changed)
        card.row("Тема", "Готовые темы, сохранённые свои и «Своя тема», где можно задать каждый цвет.", self.theme)
        self.density = _combo(DENSITY.items(), w["density"])
        self.density.currentIndexChanged.connect(lambda: self.set_work("density", self.density.currentData()))
        card.row("Плотность списков", "Сколько места между строками в боковой панели и списке.", self.density)

        card = Card(lay, "Цвета своей темы")
        card.widget(_muted("Нажми на цвет, чтобы поменять. Если выбрана готовая тема, её цвета станут "
                           "основой для «Своей темы». Понравилось - сохрани под своим именем."))
        grid_box = QWidget()
        grid = QGridLayout(grid_box)
        grid.setContentsMargins(0, 10, 0, 6)
        grid.setHorizontalSpacing(18)
        self.swatches = {}
        for i, (key, label, hint) in enumerate(th.COLOR_ROLES):
            b = QPushButton()
            b.setObjectName("swatch")
            b.setFixedSize(46, 26)
            b.setToolTip(hint)
            b.clicked.connect(lambda _=False, k=key: self.pick_color(k))
            name = QLabel(label)
            name.setToolTip(hint)
            col = (i % 2) * 2
            grid.addWidget(b, i // 2, col)
            grid.addWidget(name, i // 2, col + 1)
            self.swatches[key] = b
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        card.widget(grid_box)
        btns = QHBoxLayout()
        self.save_theme_btn = QPushButton("💾 Сохранить как тему…")
        self.save_theme_btn.clicked.connect(self.save_theme)
        self.delete_theme_btn = QPushButton("🗑 Удалить эту тему")
        self.delete_theme_btn.clicked.connect(self.delete_theme)
        for b in (self.save_theme_btn, self.delete_theme_btn):
            b.setAutoDefault(False)
            btns.addWidget(b)
        btns.addStretch(1)
        holder = QWidget()
        holder.setLayout(btns)
        card.widget(holder)

        card = Card(lay, "Текст и шрифт")
        self.font_choice = QComboBox()
        self.font_choice.addItem("Системный", "")
        self.font_choice.addItem("Inter - современный (вшит в программу)", th.BUNDLED_FONT)
        self.font_choice.addItem("Другой…", "other")
        self.font_other = QFontComboBox()
        fam = w["font_family"]
        if fam in ("", "steam", th.BUNDLED_FONT):
            self.font_choice.setCurrentIndex(self.font_choice.findData("" if fam == "steam" else fam))
            self.font_other.setVisible(False)
        else:
            self.font_choice.setCurrentIndex(2)
            self.font_other.setCurrentText(fam)
        self.font_choice.currentIndexChanged.connect(self.on_font_changed)
        self.font_other.currentFontChanged.connect(lambda f: self.set_work("font_family", f.family()))
        self.font_hint = ("Системный - как в Windows (Segoe UI). Inter - аккуратный современный шрифт, "
                          "бесплатный и уже вложен в программу. «Другой…» - любой установленный.")
        font_box = QWidget()
        fb = QVBoxLayout(font_box)
        fb.setContentsMargins(0, 0, 0, 0)
        fb.addWidget(self.font_choice)
        fb.addWidget(self.font_other)
        card.row("Шрифт", self.font_hint, font_box)
        self.font_pt = QSpinBox()
        self.font_pt.setRange(0, 20)
        self.font_pt.setSpecialValueText("как в системе")
        self.font_pt.setSuffix(" pt")
        self.font_pt.setValue(int(w["font_pt"] or 0))
        self.font_pt.valueChanged.connect(lambda v: self.set_work("font_pt", v))
        card.row("Размер текста", "Влияет на весь интерфейс.", self.font_pt)
        self.text_color_btn = QPushButton()
        self.text_color_btn.setObjectName("swatch")
        self.text_color_btn.setFixedSize(46, 26)
        self.text_color_btn.clicked.connect(self.pick_text_color)
        reset_text = QToolButton()
        reset_text.setText("из темы")
        reset_text.clicked.connect(lambda: (self.set_work("text_color", ""), self.update_swatches()))
        tc = QWidget()
        tcl = QHBoxLayout(tc)
        tcl.setContentsMargins(0, 0, 0, 0)
        tcl.addStretch(1)
        tcl.addWidget(self.text_color_btn)
        tcl.addWidget(reset_text)
        card.row("Цвет текста", "Свой цвет поверх любой темы. «из темы» - как задумано в теме.", tc)
        self.language = _combo(LANGUAGES.items(), w["language"])
        self.language.setToolTip("Другие языки появятся в следующих версиях")
        card.row("Язык", "Пока доступен только русский.", self.language)

        card = Card(lay, "Обложки в сетке")
        self.badges = QSpinBox()
        self.badges.setRange(0, 5)
        self.badges.setSpecialValueText("не показывать")
        self.badges.setValue(int(w["cover_badges"]))
        card.row("Значков тегов на обложке", "Остальные сворачиваются в «…».", self.badges)
        self.stars = _check(w["cover_stars"])
        card.row("Звёзды оценки", "В левом нижнем углу обложки.", self.stars)
        self.strip = _check(w["cover_strip"])
        card.row("Цветная полоска тегов", "Тонкая полоска цветов тегов внизу обложки.", self.strip)
        self.details = _check(w["show_details"])
        card.row("Панель деталей справа", "Оценка, теги, заметка выделенного файла. Также Ctrl+P.", self.details)
        lay.addStretch(1)
        self.update_swatches()
        return page

    def fill_theme_combo(self):
        self._filling = True
        self.theme.blockSignals(True)
        self.theme.clear()
        for key, label in th.theme_choices(self.work):
            self.theme.addItem(label, key)
        idx = self.theme.findData(self.work["theme"])
        self.theme.setCurrentIndex(idx if idx >= 0 else 0)
        self.theme.blockSignals(False)
        self._filling = False

    def current_colors(self):
        return th.colors_for(self.work["theme"], self.work) or dict(th.STEAM)

    def update_swatches(self):
        colors = self.current_colors()
        for key, b in self.swatches.items():
            b.setStyleSheet(f"QPushButton#swatch {{ background: {colors[key]}; }}")
            b.setToolTip(f"{colors[key]}")
        tc = self.work["text_color"] or colors["text"]
        self.text_color_btn.setStyleSheet(f"QPushButton#swatch {{ background: {tc}; }}")
        self.delete_theme_btn.setEnabled(str(self.work["theme"]).startswith("saved:"))

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_polished", False):
            # при самом первом показе стили применялись не ко всем строкам - применяем заново
            self._polished = True
            QTimer.singleShot(0, self.preview)

    def preview(self):
        th.apply_theme(QApplication.instance(), self.work)

    def set_work(self, key, value):
        self.work[key] = value
        self.preview()

    def on_theme_changed(self):
        if getattr(self, "_filling", False):
            return
        self.work["theme"] = self.theme.currentData()
        self.update_swatches()
        self.preview()

    def pick_color(self, key):
        colors = self.current_colors()
        c = QColorDialog.getColor(QColor(colors[key]), self, "Цвет")
        if not c.isValid():
            return
        colors[key] = c.name()
        theme = self.work["theme"]
        if theme.startswith("saved:"):                  # правим сохранённую тему
            self.work["custom_themes"] = {**self.work["custom_themes"], theme[6:]: colors}
        else:                                           # готовая тема -> «Своя тема» на её основе
            self.work["custom_colors"] = colors
            self.work["theme"] = "custom"
            self.fill_theme_combo()
        self.update_swatches()
        self.preview()

    def save_theme(self):
        name, ok = QInputDialog.getText(self, "Сохранить тему", "Название темы:")
        name = name.strip()
        if not ok or not name:
            return
        self.work["custom_themes"] = {**(self.work["custom_themes"] or {}), name: self.current_colors()}
        self.work["theme"] = f"saved:{name}"
        self.fill_theme_combo()
        self.update_swatches()

    def delete_theme(self):
        theme = self.work["theme"]
        if not theme.startswith("saved:"):
            return
        themes = dict(self.work["custom_themes"])
        themes.pop(theme[6:], None)
        self.work["custom_themes"] = themes
        self.work["theme"] = "steam"
        self.fill_theme_combo()
        self.update_swatches()
        self.preview()

    def on_font_changed(self):
        data = self.font_choice.currentData()
        self.font_other.setVisible(data == "other")
        self.set_work("font_family", self.font_other.currentFont().family() if data == "other" else data)

    def pick_text_color(self):
        c = QColorDialog.getColor(QColor(self.work["text_color"] or self.current_colors()["text"]), self, "Цвет текста")
        if c.isValid():
            self.set_work("text_color", c.name())
            self.update_swatches()

    # ================= Библиотека =================
    def _page_library(self):
        page, lay = _page("Библиотека", "Как программа показывает файлы и что делает в фоне.")
        w = self.work
        card = Card(lay, "Показ файлов")
        self.page_size = QComboBox()
        for v in (300, 500, 1000, 2000, 5000):
            self.page_size.addItem(f"по {v}", v)
        self.page_size.setCurrentIndex(max(0, self.page_size.findData(w["page_size"])))
        card.row("Файлов на экране за раз", "Остальные - по кнопке «Показать ещё». Меньше - быстрее.", self.page_size)
        self.start_view = _combo([("last", "Последний открытый раздел"), ("all", "Все файлы")], w["start_view"])
        card.row("При запуске открывать", None, self.start_view)

        card = Card(lay, "Фоновые задачи")
        self.watch = _check(w["watch_folders"])
        card.row("Следить за папками", "Новые, перемещённые и удалённые файлы замечаются сами.", self.watch)
        self.dups = _check(w["auto_duplicates"])
        card.row("Искать дубликаты", "Раздел «⧉ Дубликаты» обновляется сам.", self.dups)
        self.colors = _check(w["auto_colors"])
        card.row("Определять цвета картинок", "Нужно для поиска по цвету (🎨).", self.colors)

        card = Card(lay, "Защита")
        self.big = QSpinBox()
        self.big.setRange(5_000, 1_000_000)
        self.big.setSingleStep(5_000)
        self.big.setValue(int(w["big_folder_files"]))
        card.row("Спрашивать, если в папке больше файлов", "Защита от случайного добавления огромных папок.", self.big)
        self.confirm = _check(w["confirm_remove"])
        card.row("Подтверждать «Убрать из библиотеки»", "С диска файлы не удаляются в любом случае.", self.confirm)
        lay.addStretch(1)
        return page

    # ================= Горячие клавиши =================
    def _page_keys(self):
        page, lay = _page("Горячие клавиши", "Кликни по сочетанию и нажми новое. Пусто - без горячей клавиши. "
                                             "Клавиши без Ctrl/Alt работают только в списке файлов.")
        self.key_filter = QLineEdit()
        self.key_filter.setPlaceholderText("🔍 Найти действие…")
        self.key_filter.textChanged.connect(self.filter_keys)
        lay.addSpacing(8)
        lay.addWidget(self.key_filter)
        current = self.work["shortcuts"] or {}
        self.keys_table = QTableWidget(len(self.shortcut_defs), 3)
        self.keys_table.setHorizontalHeaderLabels(["Действие", "Клавиши", ""])
        self.keys_table.verticalHeader().setVisible(False)
        self.keys_table.verticalHeader().setDefaultSectionSize(44)   # поле клавиш помещается целиком
        self.keys_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.keys_table.setShowGrid(False)
        hdr = self.keys_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.Fixed)
        hdr.setSectionResizeMode(2, QHeaderView.Fixed)
        self.keys_table.setColumnWidth(1, 240)
        self.keys_table.setColumnWidth(2, 48)
        self.keys_table.setMinimumHeight(420)
        self.key_edits = {}
        for row, (sid, default, desc) in enumerate(self.shortcut_defs):
            item = QTableWidgetItem(desc)
            item.setFlags(Qt.ItemIsEnabled)
            self.keys_table.setItem(row, 0, item)
            edit = QKeySequenceEdit(QKeySequence(current.get(sid, default)))
            edit.setFixedHeight(32)
            holder = QWidget()
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(4, 6, 8, 6)
            hl.addWidget(edit)
            self.keys_table.setCellWidget(row, 1, holder)
            reset = QToolButton()
            reset.setText("↺")
            reset.setToolTip(f"По умолчанию: {default or 'нет'}")
            reset.clicked.connect(lambda _=False, e=edit, d=default: e.setKeySequence(QKeySequence(d)))
            self.keys_table.setCellWidget(row, 2, reset)
            self.key_edits[sid] = (edit, default)
        lay.addWidget(self.keys_table, 1)
        reset_all = QPushButton("↺ Вернуть все клавиши по умолчанию")
        reset_all.setAutoDefault(False)
        reset_all.clicked.connect(self.reset_keys)
        lay.addWidget(reset_all, 0, Qt.AlignLeft)
        return page

    def filter_keys(self, text):
        text = text.strip().lower()
        for row, (_sid, _d, desc) in enumerate(self.shortcut_defs):
            self.keys_table.setRowHidden(row, bool(text) and text not in desc.lower())

    # ================= Инструкция и О программе =================
    def _page_guide(self):
        page, lay = _page("Инструкция", "Как пользоваться программой.")
        card = Card(lay, "Обучение")
        b1 = QPushButton("🎯 Пройти обучение")
        b1.clicked.connect(lambda: self._run(self.on_tour))
        card.row("Обучение со стрелками", "Покажет прямо на экране, где какая кнопка.", b1)
        b2 = QPushButton("📖 Открыть инструкцию")
        b2.clicked.connect(lambda: self.on_guide and self.on_guide())
        card.row("Инструкция", "Подробный рассказ о всех функциях по страницам.", b2)
        lay.addStretch(1)
        return page

    def _run(self, func):
        if func:
            self.accept()   # обучение показывается на главном окне - настройки закрываем
            func()

    def _page_about(self, data_dir):
        page, lay = _page(f"Виртуальный проводник {VERSION}",
                          "Раскладывай файлы тегами и коллекциями, как игры в библиотеке Steam. "
                          "Сами файлы остаются на своих местах.")
        card = Card(lay, "Данные")
        open_btn = QPushButton("📂 Открыть папку")
        open_btn.clicked.connect(lambda: self.on_data_dir and self.on_data_dir())
        card.row("Папка данных программы", data_dir or None, open_btn)
        card = Card(lay, "Обновления")
        self.check_updates = _check(self.work["check_updates"])
        card.row("Проверять обновления", "Раз в день программа спрашивает GitHub, не вышла ли новая "
                 "версия, и предлагает её скачать. Сама ничего не устанавливает." if GITHUB_REPO else
                 "Эта копия собрана не на GitHub - проверять негде.", self.check_updates)
        upd = QPushButton("🔄 Проверить сейчас")
        upd.setEnabled(bool(GITHUB_REPO))
        upd.clicked.connect(lambda: self.on_check_updates and self.on_check_updates())
        card.row(f"Установлена версия {VERSION}",
                 f"Страница программы: github.com/{GITHUB_REPO}" if GITHUB_REPO else None, upd)
        card = Card(lay, "Если что-то сломалось")
        log_btn = QPushButton("📄 Журнал ошибок")
        log_btn.clicked.connect(lambda: self.on_open_log and self.on_open_log())
        card.row("Журнал ошибок", "Если программа показала ошибку или закрылась сама - подробности "
                 "в этом файле. Пришли его разработчику.", log_btn)
        card = Card(lay, "Сброс")
        reset = QPushButton("Сбросить настройки")
        reset.clicked.connect(self.reset_all)
        card.row("Вернуть настройки по умолчанию", "Теги, коллекции и файлы не пострадают - только "
                 "оформление и параметры. Сохранённые темы останутся.", reset)
        lay.addStretch(1)
        return page

    # ================= сохранение =================
    def reset_keys(self):
        for edit, default in self.key_edits.values():
            edit.setKeySequence(QKeySequence(default))

    def reset_all(self):
        if QMessageBox.question(self, "Сброс", "Вернуть все настройки по умолчанию?") != QMessageBox.Yes:
            return
        keep = {"onboarding_done", "window", "custom_themes", "settings_version", "update_checked", "skip_version"}
        for k, v in DEFAULTS.items():
            if k not in keep:
                self.work[k] = copy.deepcopy(v)
        self.settings.update(self.work)
        self.changed_keys |= set(DEFAULTS)
        self.preview()
        self.accept()

    def collect_shortcuts(self):
        """-> (словарь своих клавиш, список конфликтов)."""
        chosen, custom = {}, {}
        for sid, (edit, default) in self.key_edits.items():
            seq = edit.keySequence().toString(QKeySequence.PortableText)
            if seq != (default or ""):
                custom[sid] = seq
            if seq:
                chosen.setdefault(seq, []).append(sid)
        names = {sid: desc for sid, _d, desc in self.shortcut_defs}
        conflicts = [f"{seq}: " + ", ".join(names[x] for x in ids) for seq, ids in chosen.items() if len(ids) > 1]
        return custom, conflicts

    def values(self):
        v = {k: self.work[k] for k in ("theme", "custom_colors", "custom_themes", "font_family", "font_pt",
                                       "text_color", "density")}
        v.update({
            "language": self.language.currentData(), "cover_badges": self.badges.value(),
            "cover_stars": self.stars.isChecked(), "cover_strip": self.strip.isChecked(),
            "show_details": self.details.isChecked(), "page_size": self.page_size.currentData(),
            "start_view": self.start_view.currentData(), "watch_folders": self.watch.isChecked(),
            "auto_duplicates": self.dups.isChecked(), "auto_colors": self.colors.isChecked(),
            "confirm_remove": self.confirm.isChecked(), "big_folder_files": self.big.value(),
            "check_updates": self.check_updates.isChecked(),
        })
        return v

    def apply(self):
        custom, conflicts = self.collect_shortcuts()
        if conflicts:
            self.nav.setCurrentRow(2)
            QMessageBox.warning(self, "Горячие клавиши",
                                "Одно сочетание назначено на несколько действий:\n\n" + "\n".join(conflicts))
            return False
        new = self.values()
        new["shortcuts"] = custom
        changed = {k for k, v in new.items() if self.settings[k] != v}
        if changed:
            self.settings.update(new)
            self.changed_keys |= changed
            if self.on_apply:
                self.on_apply(changed)
        return True

    def on_ok(self):
        if self.apply():
            self.accept()

    def reject(self):
        # отмена: вернуть оформление к сохранённым настройкам (предпросмотр мог его поменять)
        th.apply_theme(QApplication.instance(), self.settings)
        super().reject()
