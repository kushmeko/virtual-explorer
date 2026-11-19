"""Диалоги:
  * TagEditorDialog         - "Мои метки" как в Steam: поиск, популярные, отметить галочками
                              (работает сразу для нескольких выделенных файлов)
  * TagManagerDialog        - менеджер тегов: имя, цвет, группа, слияние, удаление
  * DynamicCollectionDialog - правила динамической коллекции
  * LibraryFoldersDialog    - папки библиотеки, за которыми следим
  * AutoRulesDialog         - правила авто-тегов ("лежит в папке Школа" -> тег Школа)
  * FoldersToTagsDialog     - «Папки → теги»: превратить свои папки в теги в один клик
  * BackupsDialog           - резервные копии базы: сделать / восстановить
  * CandidatesDialog        - варианты, где может быть потерянный файл
"""
import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
)

from app import backup
from app.db import AUTO_GROUP
from app.ui import icons as tag_icons


def color_icon(color, size=14):
    pix = QPixmap(size, size)
    pix.fill(QColor(color))
    return QIcon(pix)


TOP_LEVEL = "- верхний уровень -"
INDENT = "\u2003\u2003"   # отступ вложенного тега в таблице (широкие пробелы)


def tag_label(tag, count_text="", path=None):
    """«Кошки (3) · Животные › Кошки» - для вложенных тегов показываем полный путь."""
    grp = f"   · {tag['grp']}" if tag["grp"] else ""
    where = f"   ⟵ {path.rsplit(' › ', 1)[0]}" if path and " › " in path else ""
    return f"{tag['name']}{count_text}{where}{grp}"


def clean_name(text):
    """Убирает отступ и «└» из ячейки с названием перед переименованием."""
    return text.lstrip("\u2003 └").strip()


def tree_order(tags, key=None):
    """Теги в порядке дерева: родитель, сразу под ним его вложенные. -> [(тег, глубина)]."""
    by_parent = {}
    ids = {t["id"] for t in tags}
    for t in tags:
        pid = t["parent_id"] if t["parent_id"] in ids else None
        by_parent.setdefault(pid, []).append(t)
    key = key or (lambda t: (-t["cnt"], t["name"].lower()))
    out, seen = [], set()

    def walk(pid, depth):
        for t in sorted(by_parent.get(pid, []), key=key):
            if t["id"] in seen:
                continue
            seen.add(t["id"])
            out.append((t, depth))
            walk(t["id"], depth + 1)

    walk(None, 0)
    out.extend((t, 0) for t in tags if t["id"] not in seen)  # на случай битых ссылок
    return out


def choose_parent(widget, db, tag_ids, title="Вложить в тег"):
    """Окно выбора родителя. -> (ok, parent_id или None)."""
    banned = set(tag_ids)
    for tid in tag_ids:
        banned |= db.descendants(tid)
    paths = db.tag_paths()
    options = sorted((p, tid) for tid, p in paths.items() if tid not in banned)
    labels = [TOP_LEVEL] + [p for p, _ in options]
    current = db.get_tag(tag_ids[0])["parent_id"] if len(tag_ids) == 1 else None
    idx = next((i + 1 for i, (_p, tid) in enumerate(options) if tid == current), 0)
    choice, ok = QInputDialog.getItem(
        widget, title,
        "Внутри какого тега будет этот тег?\n"
        "Фильтр по родителю покажет и файлы вложенных тегов.", labels, idx, False)
    if not ok:
        return False, None
    return True, (None if choice == TOP_LEVEL else dict(options)[choice])


# ======================================================================
class TagEditorDialog(QDialog):
    """Окно "Метки" для одного или нескольких файлов.

    Галочка - тег будет у всех выделенных, пусто - ни у кого,
    "квадратик" (частично) - оставить как есть.
    """

    def __init__(self, db, file_ids, parent=None):
        super().__init__(parent)
        self.db = db
        self.file_ids = list(file_ids)
        n = len(self.file_ids)
        self.setWindowTitle("Метки" if n == 1 else f"Метки для {n} файлов")
        self.resize(420, 520)

        if n == 1:
            head = f"Файл: <b>{db.get_file(self.file_ids[0])['name']}</b>"
        else:
            head = f"Выделено файлов: <b>{n}</b>. Квадратик ◪ - тег есть у части файлов."
        info = QLabel(head)
        info.setWordWrap(True)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Найти метку или ввести новую и нажать Enter")
        self.search.textChanged.connect(self.apply_search)
        self.create_btn = QPushButton("＋ Создать")
        self.create_btn.clicked.connect(self.create_from_search)
        row = QHBoxLayout()
        row.addWidget(self.search, 1)
        row.addWidget(self.create_btn)

        self.list = QListWidget()
        self.list.itemClicked.connect(self.on_item_clicked)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(info)
        layout.addLayout(row)
        layout.addWidget(QLabel("Популярные метки (больше всего файлов - выше):"))
        layout.addWidget(self.list, 1)
        layout.addWidget(buttons)

        self.initial = {}   # id тега -> исходное состояние
        self.fill()
        self.search.setFocus()

    def fill(self, check_ids=()):
        have = {t["id"]: t["cnt"] for t in self.db.get_tags_for_files(self.file_ids)}
        n = len(self.file_ids)
        current = {
            self.list.item(i).data(Qt.UserRole): self.list.item(i).checkState()
            for i in range(self.list.count())
        }
        self.list.clear()
        paths = self.db.tag_paths()
        for tag in self.db.get_tags_with_counts():
            k = have.get(tag["id"], 0)
            initial = Qt.Checked if k == n else (Qt.PartiallyChecked if k else Qt.Unchecked)
            self.initial.setdefault(tag["id"], initial)
            item = QListWidgetItem(tag_icons.badge_icon(tag),
                                   tag_label(tag, f"   ({tag['cnt']})", paths.get(tag["id"])))
            item.setData(Qt.UserRole, tag["id"])
            item.setData(Qt.UserRole + 1, tag["name"])
            # галочку переключаем сами в on_item_clicked (клик по всей строке)
            item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
            state = current.get(tag["id"], initial)
            if tag["id"] in check_ids:
                state = Qt.Checked
            item.setCheckState(state)
            if tag["is_auto"]:
                item.setToolTip("Авто-тег по расширению файла")
            self.list.addItem(item)
        self.apply_search()

    def on_item_clicked(self, item):
        """Клик в любом месте строки переключает галочку.

        Для тега, который есть у части файлов: ◪ как есть → ✓ всем → ☐ никому → ◪.
        """
        tid = item.data(Qt.UserRole)
        state = item.checkState()
        if state == Qt.Checked:
            state = Qt.Unchecked
        elif state == Qt.Unchecked and self.initial.get(tid) == Qt.PartiallyChecked:
            state = Qt.PartiallyChecked
        else:
            state = Qt.Checked
        item.setCheckState(state)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Space and self.list.hasFocus() and self.list.currentItem():
            self.on_item_clicked(self.list.currentItem())
            return
        if key in (Qt.Key_Return, Qt.Key_Enter) and self.search.hasFocus() and self.search.text().strip():
            # Enter в поиске: отметить найденный тег или создать новый - окно не закрываем
            self.check_or_create_from_search()
            return
        super().keyPressEvent(event)

    def check_or_create_from_search(self):
        text = self.search.text().strip().lower()
        visible = [
            self.list.item(i) for i in range(self.list.count())
            if not self.list.item(i).isHidden()
        ]
        exact = [it for it in visible if it.data(Qt.UserRole + 1).lower() == text]
        if exact or len(visible) == 1:
            (exact or visible)[0].setCheckState(Qt.Checked)
            self.search.clear()
        else:
            self.create_from_search()

    def apply_search(self):
        text = self.search.text().strip().lower()
        exact = False
        for i in range(self.list.count()):
            item = self.list.item(i)
            name = item.data(Qt.UserRole + 1).lower()
            item.setHidden(bool(text) and text not in name)
            exact = exact or name == text
        self.create_btn.setEnabled(bool(text) and not exact)

    def create_from_search(self):
        text = self.search.text().strip()
        if not text:
            return
        tag_id = self.db.ensure_tag(text)
        self.search.clear()
        self.fill(check_ids={tag_id})

    def apply(self):
        """Записывает изменения в базу. Возвращает True, если что-то поменялось."""
        changed = False
        for i in range(self.list.count()):
            item = self.list.item(i)
            tid, state = item.data(Qt.UserRole), item.checkState()
            if state == self.initial.get(tid, Qt.Unchecked) or state == Qt.PartiallyChecked:
                continue
            if state == Qt.Checked:
                self.db.tag_files(self.file_ids, tid)
            else:
                self.db.untag_files(self.file_ids, tid)
            changed = True
        return changed


# ======================================================================
class TagManagerDialog(QDialog):
    """Все теги таблицей: двойной клик по имени/группе - правка, по цвету - выбор цвета."""

    COL_COLOR, COL_NAME, COL_PARENT, COL_GROUP, COL_COUNT = range(5)

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Менеджер тегов")
        self.resize(760, 540)

        self.filter = QLineEdit()
        self.filter.setPlaceholderText("🔍 Найти тег...")
        self.filter.textChanged.connect(self.apply_filter)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Цвет", "Название", "Входит в", "Группа", "Файлов"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(self.COL_NAME, QHeaderView.Stretch)
        self.table.setColumnWidth(self.COL_COLOR, 50)
        self.table.setColumnWidth(self.COL_PARENT, 170)
        self.table.setColumnWidth(self.COL_GROUP, 130)
        self.table.setColumnWidth(self.COL_COUNT, 70)
        self.table.itemChanged.connect(self.on_item_changed)
        self.table.cellDoubleClicked.connect(self.on_double_click)

        side = QVBoxLayout()
        for text, slot in [
            ("＋ Новый тег", self.new_tag),
            ("＋ Вложенный тег…", self.new_child),
            ("↳ Вложить в…", self.set_parent),
            ("🎨 Цвет…", self.pick_color),
            ("🖼 Значок…", self.edit_icon),
            ("📁 Группа…", self.set_group),
            ("⤵ Объединить…", self.merge),
            ("🗑 Удалить", self.delete),
        ]:
            btn = QPushButton(text)
            btn.setAutoDefault(False)
            btn.clicked.connect(slot)
            side.addWidget(btn)
        side.addStretch(1)
        hint = QLabel(
            "Вложенные теги: «Кошки» внутри «Животные» - фильтр по «Животные» покажет и кошек.\n\n"
            "Группы - как «Жанр» и «Тематика» в Steam: теги одной группы стоят рядом в фильтре.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #868e96;")
        side.addWidget(hint)

        body = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(self.filter)
        left.addWidget(self.table, 1)
        body.addLayout(left, 1)
        body.addLayout(side)

        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addLayout(body, 1)
        layout.addWidget(close)
        self.fill()

    def fill(self):
        self.table.blockSignals(True)
        tags = tree_order(self.db.get_tags_with_counts())
        paths = self.db.tag_paths()
        self.table.setRowCount(len(tags))
        for row, (t, depth) in enumerate(tags):
            color = QTableWidgetItem("")
            color.setBackground(QBrush(QColor(t["color"])))
            color.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            color.setToolTip("Двойной клик - выбрать цвет")
            name = QTableWidgetItem((INDENT * depth + "└ " if depth else "") + t["name"])
            name.setData(Qt.UserRole, t["id"])
            name.setIcon(tag_icons.badge_icon(t))
            name.setToolTip(paths.get(t["id"], t["name"]) +
                            ("\nАвто-тег по расширению" if t["is_auto"] else ""))
            parent_path = paths.get(t["parent_id"], "") if t["parent_id"] else ""
            parent = QTableWidgetItem(parent_path)
            parent.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            parent.setToolTip("Двойной клик - вложить в другой тег")
            group = QTableWidgetItem(t["grp"])
            count = QTableWidgetItem(str(t["cnt"]))
            count.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            count.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            for col, it in enumerate((color, name, parent, group, count)):
                self.table.setItem(row, col, it)
        self.table.blockSignals(False)
        self.apply_filter()

    def apply_filter(self):
        text = self.filter.text().strip().lower()
        for row in range(self.table.rowCount()):
            name = self.table.item(row, self.COL_NAME).text().lower()
            grp = self.table.item(row, self.COL_GROUP).text().lower()
            self.table.setRowHidden(row, bool(text) and text not in name and text not in grp)

    def tag_id(self, row):
        return self.table.item(row, self.COL_NAME).data(Qt.UserRole)

    def selected_ids(self):
        rows = sorted({i.row() for i in self.table.selectedItems()})
        return [self.tag_id(r) for r in rows]

    def on_item_changed(self, item):
        tid = self.tag_id(item.row())
        if item.column() == self.COL_NAME:
            if not self.db.rename_tag(tid, clean_name(item.text())):
                QMessageBox.warning(self, "Ошибка", "Такой тег уже есть (или название пустое).")
        elif item.column() == self.COL_GROUP:
            self.db.set_tag_group(tid, item.text())
        QTimer.singleShot(0, self.fill)  # перерисуем после выхода из обработчика

    def on_double_click(self, row, col):
        if col == self.COL_COLOR:
            self.table.selectRow(row)
            self.pick_color()
        elif col == self.COL_PARENT:
            self.table.selectRow(row)
            self.set_parent()

    def new_tag(self):
        name, ok = QInputDialog.getText(self, "Новый тег", "Название:")
        if ok and name.strip():
            self.db.ensure_tag(name)
            self.fill()

    def new_child(self):
        ids = self.selected_ids()
        if not ids:
            QMessageBox.information(self, "Вложенный тег", "Сначала выбери тег-родитель в таблице.")
            return
        parent = self.db.get_tag(ids[0])
        name, ok = QInputDialog.getText(self, "Вложенный тег", f"Новый тег внутри «{parent['name']}»:")
        if ok and name.strip():
            tid = self.db.ensure_tag(name)
            if not self.db.set_parent(tid, parent["id"]):
                QMessageBox.warning(self, "Ошибка", "Нельзя вложить тег сам в себя.")
            self.fill()

    def set_parent(self):
        ids = self.selected_ids()
        if not ids:
            return
        ok, parent_id = choose_parent(self, self.db, ids)
        if ok:
            for tid in ids:
                self.db.set_parent(tid, parent_id)
            self.fill()

    def edit_icon(self):
        ids = self.selected_ids()
        if not ids:
            return
        dlg = TagIconDialog(self.db, ids[0], self)
        if dlg.exec() == QDialog.Accepted:
            dlg.apply()
            self.changed_icons = True
            self.fill()

    def pick_color(self):
        ids = self.selected_ids()
        if not ids:
            return
        start = QColor(self.db.get_tag(ids[0])["color"])
        color = QColorDialog.getColor(start, self, "Цвет тега")
        if color.isValid():
            for tid in ids:
                self.db.set_tag_color(tid, color.name())
            self.fill()

    def set_group(self):
        ids = self.selected_ids()
        if not ids:
            return
        groups = [""] + self.db.get_groups()
        if AUTO_GROUP not in groups:
            groups.append(AUTO_GROUP)
        grp, ok = QInputDialog.getItem(
            self, "Группа", f"Группа для тегов ({len(ids)}).\nМожно вписать новую, пусто - без группы:",
            groups, 0, True,
        )
        if ok:
            self.db.set_tag_group(ids, grp)
            self.fill()

    def merge(self):
        ids = self.selected_ids()
        if not ids:
            return
        tags = self.db.get_tags_with_counts()
        names = [t["name"] for t in tags]
        default = self.db.get_tag(ids[0])["name"]
        target, ok = QInputDialog.getItem(
            self, "Объединить теги",
            f"Выбранные теги ({len(ids)}) станут одним тегом.\nВ какой тег слить?",
            names, names.index(default) if default in names else 0, False,
        )
        if not ok:
            return
        target_id = next(t["id"] for t in tags if t["name"] == target)
        backup.make_backup(self.db.conn, "merge-tags")
        self.db.merge_tags(ids, target_id)
        self.fill()

    def delete(self):
        ids = self.selected_ids()
        if not ids:
            return
        answer = QMessageBox.question(
            self, "Удалить", f"Удалить тегов: {len(ids)}?\nФайлы на диске не пострадают."
        )
        if answer == QMessageBox.Yes:
            backup.make_backup(self.db.conn, "delete-tag")
            for tid in ids:
                self.db.delete_tag(tid)
            self.fill()


# ======================================================================
STATE_MARK = {"off": "    ", "include": "✓  ", "exclude": "✕  "}
STATE_NEXT = {"off": "include", "include": "exclude", "exclude": "off"}


class DynamicCollectionDialog(QDialog):
    def __init__(self, db, parent=None, name="", rules=None):
        super().__init__(parent)
        rules = rules or {}
        self.setWindowTitle("Динамическая коллекция")
        self.resize(420, 540)

        self.name_edit = QLineEdit(name)

        self.mode_box = QComboBox()
        self.mode_box.addItem("все отмеченные (И)", "all")
        self.mode_box.addItem("любой из отмеченных (ИЛИ)", "any")
        self.mode_box.setCurrentIndex(1 if rules.get("tag_mode") == "any" else 0)

        self.tags_list = QListWidget()
        self.tags_list.setToolTip("Клик: ✓ нужен → ✕ исключить → не важно")
        self.tags_list.itemClicked.connect(self.cycle)
        inc, exc = set(rules.get("tags", [])), set(rules.get("exclude_tags", []))
        paths = db.tag_paths()
        for tag, _depth in tree_order(db.get_tags_with_counts()):
            item = QListWidgetItem()
            item.setData(Qt.UserRole, tag["id"])
            item.setData(Qt.UserRole + 1, tag_label(tag, path=paths.get(tag["id"])))
            item.setData(Qt.UserRole + 2, tag["color"])
            state = "include" if tag["id"] in inc else ("exclude" if tag["id"] in exc else "off")
            self._set_state(item, state)
            self.tags_list.addItem(item)

        self.exts_edit = QLineEdit(" ".join(rules.get("exts", [])))
        self.exts_edit.setPlaceholderText(".pdf .docx")

        self.min_kb = QSpinBox()
        self.min_kb.setRange(0, 100_000_000)
        self.min_kb.setSuffix(" КБ")
        self.min_kb.setSpecialValueText("не важно")
        self.min_kb.setValue(rules.get("min_kb", 0))

        self.query_edit = QLineEdit(rules.get("query", ""))
        self.query_edit.setPlaceholderText("как в строке поиска: #Школа .pdf размер>1мб")

        self.days = QSpinBox()
        self.days.setRange(0, 3650)
        self.days.setSuffix(" дн.")
        self.days.setSpecialValueText("не важно")
        self.days.setValue(rules.get("days", 0))

        form = QFormLayout()
        form.addRow("Название", self.name_edit)
        form.addRow("Нужны теги", self.mode_box)
        form.addRow("Теги\n(клик: ✓ / ✕ / -)", self.tags_list)
        form.addRow("Расширения", self.exts_edit)
        form.addRow("Размер от", self.min_kb)
        form.addRow("Добавлены за последние", self.days)
        form.addRow("Поиск", self.query_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    @staticmethod
    def _set_state(item, state):
        item.setData(Qt.UserRole + 3, state)
        item.setText(STATE_MARK[state] + item.data(Qt.UserRole + 1))
        if state == "include":
            item.setForeground(QBrush(QColor(item.data(Qt.UserRole + 2))))
        elif state == "exclude":
            item.setForeground(QBrush(QColor("#e03131")))
        else:
            item.setData(Qt.ForegroundRole, None)
        font = item.font()
        font.setStrikeOut(state == "exclude")
        font.setBold(state == "include")
        item.setFont(font)

    def cycle(self, item):
        self._set_state(item, STATE_NEXT[item.data(Qt.UserRole + 3)])

    def result_data(self):
        """Возвращает (название, словарь правил)."""
        rules = {}
        inc, exc = [], []
        for i in range(self.tags_list.count()):
            item = self.tags_list.item(i)
            state = item.data(Qt.UserRole + 3)
            if state == "include":
                inc.append(item.data(Qt.UserRole))
            elif state == "exclude":
                exc.append(item.data(Qt.UserRole))
        if inc:
            rules["tags"] = inc
            if self.mode_box.currentData() == "any":
                rules["tag_mode"] = "any"
        if exc:
            rules["exclude_tags"] = exc
        exts = [
            e if e.startswith(".") else "." + e
            for e in self.exts_edit.text().lower().replace(",", " ").split()
        ]
        if exts:
            rules["exts"] = exts
        if self.min_kb.value():
            rules["min_kb"] = self.min_kb.value()
        if self.days.value():
            rules["days"] = self.days.value()
        if self.query_edit.text().strip():
            rules["query"] = self.query_edit.text().strip()
        return self.name_edit.text().strip(), rules


# ======================================================================
class LibraryFoldersDialog(QDialog):
    """Папки библиотеки - как "Папки библиотеки Steam".

    В этих папках новые файлы добавляются сами, а перемещённые внутри них - находятся.
    """

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.changed = False
        self.requested_add = None
        self.setWindowTitle("Папки библиотеки")
        self.resize(560, 360)

        info = QLabel(
            "За этими папками программа следит: новые файлы появляются в библиотеке сами, "
            "а перемещённые и переименованные внутри них - находятся вместе с тегами."
        )
        info.setWordWrap(True)
        self.list = QListWidget()

        add = QPushButton("＋ Добавить папку…")
        add.setAutoDefault(False)
        add.clicked.connect(self.add)
        remove = QPushButton("− Убрать папку")
        remove.setAutoDefault(False)
        remove.clicked.connect(self.remove)
        self.unhide_btn = QPushButton("")
        self.unhide_btn.setAutoDefault(False)
        self.unhide_btn.setToolTip("Файлы, которые ты убрал из библиотеки, снова появятся при проверке")
        self.unhide_btn.clicked.connect(self.unhide)
        row = QHBoxLayout()
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        row.addWidget(self.unhide_btn)

        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addWidget(info)
        layout.addWidget(self.list, 1)
        layout.addLayout(row)
        layout.addWidget(close)
        self.fill()

    def fill(self):
        self.list.clear()
        for path in self.db.get_folders():
            self.list.addItem(path)
        n = len(self.db.hidden_keys())
        self.unhide_btn.setText(f"↩ Вернуть убранные файлы ({n})")
        self.unhide_btn.setEnabled(n > 0)

    def unhide(self):
        self.db.unhide_all()
        self.changed = True
        self.fill()

    def add(self):
        folder = QFileDialog.getExistingDirectory(self, "Выбери папку")
        if folder:
            # само добавление - в главном окне: в фоне, с проверкой и прогрессом
            self.requested_add = folder
            self.accept()

    def remove(self):
        item = self.list.currentItem()
        if item is None:
            return
        box = QMessageBox(self)
        box.setWindowTitle("Убрать папку")
        box.setText(f"Перестать следить за папкой?\n{item.text()}")
        box.setInformativeText("Файлы на диске не пострадают. Что сделать с ними в библиотеке?")
        keep = box.addButton("Оставить в библиотеке", QMessageBox.AcceptRole)
        drop = box.addButton("Убрать из библиотеки", QMessageBox.DestructiveRole)
        box.addButton("Отмена", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() not in (keep, drop):
            return
        if box.clickedButton() is drop:
            backup.make_backup(self.db.conn, "remove-folder")
        self.db.remove_watched_folder(item.text(), remove_files=box.clickedButton() is drop)
        self.changed = True
        self.fill()


# ======================================================================
class AutoRulesDialog(QDialog):
    """Правила авто-тегов. Работают для новых файлов сами, для старых - кнопкой."""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.changed = False
        self.setWindowTitle("Правила авто-тегов")
        self.resize(640, 480)

        info = QLabel(
            "Программа сама ставит тег, если файл подходит под правило. "
            "Например: <b>лежит в папке</b> «Школа» → тег <b>Школа</b>; "
            "<b>имя файла</b> «скриншот*» → тег <b>Скриншоты</b>. "
            "Новые файлы получают теги сразу, для уже добавленных - кнопка «Применить»."
        )
        info.setWordWrap(True)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Вкл.", "Тег", "Условие", "Значение"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 44)
        self.table.setColumnWidth(1, 150)
        self.table.setColumnWidth(2, 130)
        self.table.itemChanged.connect(self.on_item_changed)

        # строка добавления правила
        self.tag_box = QComboBox()
        self.tag_box.setEditable(True)
        self.tag_box.setMinimumWidth(140)
        self.tag_box.lineEdit().setPlaceholderText("тег")
        self.kind_box = QComboBox()
        for kind, label in db.RULE_KINDS.items():
            self.kind_box.addItem(label, kind)
        self.value_edit = QLineEdit()
        self.value_edit.setPlaceholderText("Школа  /  скриншот*  /  .psd .ai")
        self.value_edit.textChanged.connect(self.update_preview)
        self.kind_box.currentIndexChanged.connect(self.update_preview)
        add = QPushButton("＋ Добавить")
        add.setAutoDefault(False)
        add.clicked.connect(self.add_rule)
        self.preview = QLabel("")
        self.preview.setStyleSheet("color: #868e96;")
        add_row = QHBoxLayout()
        add_row.addWidget(QLabel("Тег"))
        add_row.addWidget(self.tag_box)
        add_row.addWidget(QLabel("если"))
        add_row.addWidget(self.kind_box)
        add_row.addWidget(self.value_edit, 1)
        add_row.addWidget(add)

        delete = QPushButton("🗑 Удалить правило")
        delete.setAutoDefault(False)
        delete.clicked.connect(self.delete_rule)
        folders = QPushButton("📁 Папки → теги…")
        folders.setAutoDefault(False)
        folders.setToolTip("Создать теги и правила из имён твоих папок")
        folders.clicked.connect(self.folders_to_tags)
        apply_btn = QPushButton("▶ Применить ко всем файлам")
        apply_btn.setAutoDefault(False)
        apply_btn.clicked.connect(self.apply_all)
        buttons = QHBoxLayout()
        buttons.addWidget(delete)
        buttons.addWidget(folders)
        buttons.addStretch(1)
        buttons.addWidget(apply_btn)

        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addWidget(info)
        layout.addWidget(self.table, 1)
        layout.addLayout(add_row)
        layout.addWidget(self.preview)
        layout.addLayout(buttons)
        layout.addWidget(close)
        self.fill()

    def fill(self):
        self.table.blockSignals(True)
        rules = self.db.get_rules()
        self.table.setRowCount(len(rules))
        for row, r in enumerate(rules):
            on = QTableWidgetItem("")
            on.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            on.setCheckState(Qt.Checked if r["enabled"] else Qt.Unchecked)
            on.setData(Qt.UserRole, r["id"])
            tag = QTableWidgetItem(color_icon(r["tag_color"]), r["tag_name"])
            kind = QTableWidgetItem(self.db.RULE_KINDS.get(r["kind"], r["kind"]))
            value = QTableWidgetItem(r["value"])
            for col, it in enumerate((on, tag, kind, value)):
                self.table.setItem(row, col, it)
        self.table.blockSignals(False)
        current = self.tag_box.currentText()
        self.tag_box.clear()
        self.tag_box.addItems([t["name"] for t in self.db.get_tags_with_counts() if not t["is_auto"]])
        self.tag_box.setEditText(current)

    def on_item_changed(self, item):
        if item.column() == 0:
            self.db.set_rule_enabled(item.data(Qt.UserRole), item.checkState() == Qt.Checked)
            self.changed = True

    def update_preview(self):
        value = self.value_edit.text().strip()
        if not value:
            self.preview.setText("")
            return
        n = self.db.rule_preview_count(self.kind_box.currentData(), value)
        self.preview.setText(f"Под это условие сейчас подходит файлов: {n}")

    def add_rule(self):
        name = self.tag_box.currentText().strip()
        value = self.value_edit.text().strip()
        if not name or not value:
            QMessageBox.information(self, "Правило", "Нужны тег и значение условия.")
            return
        tid = self.db.ensure_tag(name)
        rid = self.db.add_rule(tid, self.kind_box.currentData(), value)
        added = self.db.apply_rules_all([rid])
        self.changed = True
        self.value_edit.clear()
        self.fill()
        self.preview.setText(f"Правило добавлено, тег «{name}» поставлен файлам: {added}")

    def delete_rule(self):
        rows = sorted({i.row() for i in self.table.selectedItems()})
        if not rows:
            return
        for r in rows:
            self.db.delete_rule(self.table.item(r, 0).data(Qt.UserRole))
        self.changed = True
        self.fill()
        self.preview.setText("Правило удалено. Уже поставленные теги остались.")

    def apply_all(self):
        added = self.db.apply_rules_all()
        self.changed = True
        self.preview.setText(f"Готово: поставлено тегов {added}")

    def folders_to_tags(self):
        dlg = FoldersToTagsDialog(self.db, self)
        if dlg.exec() == QDialog.Accepted and dlg.created:
            self.changed = True
            self.fill()
            self.preview.setText(f"Из папок создано правил: {dlg.created}, тегов поставлено: {dlg.tagged}")


class FoldersToTagsDialog(QDialog):
    """Твои папки уже и есть категории. Отметь нужные - каждая станет тегом с правилом."""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.created = self.tagged = 0
        self.setWindowTitle("Папки → теги")
        self.resize(460, 520)
        info = QLabel(
            "Отметь папки - каждая станет тегом с тем же названием, и все файлы в ней "
            "(включая вложенные папки) получат этот тег. Новые файлы в этих папках - тоже. "
            "Файлы никуда не перемещаются."
        )
        info.setWordWrap(True)
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍 Найти папку…")
        self.search.textChanged.connect(self.apply_search)
        self.list = QListWidget()
        existing = {t["name"].lower() for t in db.get_tags_with_counts()}
        for name, n in db.folder_name_stats():
            item = QListWidgetItem(f"{name}   ({n})")
            item.setData(Qt.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            if name.lower() in existing:
                item.setToolTip("Тег с таким названием уже есть - правило добавится к нему")
            self.list.addItem(item)
        if self.list.count() == 0:
            empty = QListWidgetItem("В папках библиотеки нет вложенных папок")
            empty.setFlags(Qt.NoItemFlags)
            self.list.addItem(empty)
        self.group_edit = QLineEdit("Папки")
        self.nest_box = QCheckBox("Вложенные папки → вложенные теги (Школа › Математика)")
        self.nest_box.setChecked(True)
        form = QFormLayout()
        form.addRow("Группа для новых тегов", self.group_edit)
        form.addRow(self.nest_box)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Создать теги")
        buttons.accepted.connect(self.create)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(info)
        layout.addWidget(self.search)
        layout.addWidget(self.list, 1)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def apply_search(self):
        text = self.search.text().strip().lower()
        for i in range(self.list.count()):
            item = self.list.item(i)
            name = item.data(Qt.UserRole) or ""
            item.setHidden(bool(text) and text not in name.lower())

    def create(self):
        rule_ids, created = [], {}
        for i in range(self.list.count()):
            item = self.list.item(i)
            name = item.data(Qt.UserRole)
            if name and item.checkState() == Qt.Checked:
                tid = self.db.ensure_tag(name, grp=self.group_edit.text())
                created[name.lower()] = tid
                rule_ids.append(self.db.add_rule(tid, "folder", name))
        if self.nest_box.isChecked():
            parents = self.db.folder_parents()
            for child, tid in created.items():
                parent = parents.get(child)
                if parent and parent.lower() in created and self.db.get_tag(tid)["parent_id"] is None:
                    self.db.set_parent(tid, created[parent.lower()])
        self.created = len(rule_ids)
        if rule_ids:
            self.tagged = self.db.apply_rules_all(rule_ids)
        self.accept()


# ======================================================================
class BackupsDialog(QDialog):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.restored = False
        self.setWindowTitle("Резервные копии")
        self.resize(560, 420)
        info = QLabel(
            "Копии базы (теги, коллекции, правила) делаются сами: раз в день и перед опасными "
            f"действиями. Хранятся последние {backup.KEEP}. Сами файлы в копии не входят - "
            "они и так на диске."
        )
        info.setWordWrap(True)
        self.list = QListWidget()
        make = QPushButton("💾 Сделать копию сейчас")
        make.setAutoDefault(False)
        make.clicked.connect(self.make)
        restore = QPushButton("↩ Восстановить выбранную…")
        restore.setAutoDefault(False)
        restore.clicked.connect(self.restore)
        folder = QPushButton("📂 Открыть папку")
        folder.setAutoDefault(False)
        folder.clicked.connect(self.open_folder)
        row = QHBoxLayout()
        row.addWidget(make)
        row.addWidget(restore)
        row.addStretch(1)
        row.addWidget(folder)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addWidget(info)
        layout.addWidget(self.list, 1)
        layout.addLayout(row)
        layout.addWidget(close)
        self.fill()

    def fill(self):
        self.list.clear()
        for path, when, reason, size in backup.list_backups():
            why = backup.REASONS.get(reason, reason)
            item = QListWidgetItem(f"{when:%d.%m.%Y %H:%M}   ·   {why}   ·   {size / 1024:.0f} КБ")
            item.setData(Qt.UserRole, str(path))
            self.list.addItem(item)

    def make(self):
        backup.make_backup(self.db.conn, "manual")
        self.fill()

    def restore(self):
        item = self.list.currentItem()
        if item is None:
            return
        answer = QMessageBox.question(
            self, "Восстановить",
            f"Вернуть базу к состоянию:\n{item.text()}?\n\n"
            "Текущее состояние тоже сохранится копией - можно будет вернуться.",
        )
        if answer == QMessageBox.Yes:
            backup.restore(self.db.conn, item.data(Qt.UserRole))
            self.restored = True
            self.fill()

    def open_folder(self):
        import os
        os.startfile(str(backup.backups_dir()))  # только Windows


# ======================================================================
class CandidatesDialog(QDialog):
    """Варианты, где теперь потерянный файл. Выбираешь - теги переезжают к нему."""

    def __init__(self, file_row, candidates, parent=None):
        super().__init__(parent)
        self.chosen = None
        self.setWindowTitle(f"Где теперь «{file_row['name']}»?")
        self.resize(760, 380)
        if candidates:
            text = (f"Нашёл похожих файлов: {len(candidates)}. Лучшие - сверху. "
                    "Выбери нужный: теги, коллекции и ★ перейдут к нему.")
        else:
            text = ("Похожих файлов в папках библиотеки и рядом со старым местом не нашлось. "
                    "Можно показать файл вручную.")
        info = QLabel(text)
        info.setWordWrap(True)
        self.table = QTableWidget(len(candidates), 4)
        self.table.setHorizontalHeaderLabels(["Файл", "Почему подходит", "Размер", "Изменён"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setColumnWidth(1, 220)
        from datetime import datetime
        for row, (path, size, mtime, _score, why) in enumerate(candidates):
            name = QTableWidgetItem(path)
            name.setData(Qt.UserRole, path)
            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, QTableWidgetItem(why))
            self.table.setItem(row, 2, QTableWidgetItem(f"{size / 1024:.0f} КБ"))
            self.table.setItem(row, 3, QTableWidgetItem(datetime.fromtimestamp(mtime).strftime("%d.%m.%Y")))
        if candidates:
            self.table.selectRow(0)
        self.table.cellDoubleClicked.connect(lambda *_: self.choose())
        manual = QPushButton("🔍 Показать вручную…")
        manual.setAutoDefault(False)
        manual.clicked.connect(self.manual)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Это он")
        buttons.button(QDialogButtonBox.Ok).setEnabled(bool(candidates))
        buttons.accepted.connect(self.choose)
        buttons.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(manual)
        bottom.addStretch(1)
        bottom.addWidget(buttons)
        layout = QVBoxLayout(self)
        layout.addWidget(info)
        layout.addWidget(self.table, 1)
        layout.addLayout(bottom)
        self.start_dir = ""

    def choose(self):
        rows = sorted({i.row() for i in self.table.selectedItems()})
        if rows:
            self.chosen = self.table.item(rows[0], 0).data(Qt.UserRole)
            self.accept()

    def manual(self):
        path, _ = QFileDialog.getOpenFileName(self, self.windowTitle(), self.start_dir)
        if path:
            self.chosen = path
            self.accept()


# ======================================================================
class TagIconDialog(QDialog):
    """Значок тега: цвет, символ (эмодзи/буква) или своя картинка (сама уменьшится)."""

    def __init__(self, db, tag_id, parent=None):
        super().__init__(parent)
        from app.db import AUTO_ICONS
        from app.ui import icons
        self.db, self.icons = db, icons
        self.tag = dict(db.get_tag(tag_id))
        self.default_symbol = AUTO_ICONS.get(self.tag["name"], "") if self.tag["is_auto"] else ""
        self.setWindowTitle(f"Значок тега «{self.tag['name']}»")
        self.resize(460, 420)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(110)
        self.preview_small = QLabel()

        color_btn = QPushButton("🎨 Цвет…")
        color_btn.setAutoDefault(False)
        color_btn.clicked.connect(self.pick_color)

        self.symbol_edit = QLineEdit(self.tag["icon"] or "")
        self.symbol_edit.setMaxLength(4)
        self.symbol_edit.setPlaceholderText(f"пусто - буква «{self.tag['name'][:1].upper()}»")
        self.symbol_edit.textChanged.connect(self.on_symbol)

        grid = QGridLayout()
        for i, sym in enumerate(icons.QUICK_SYMBOLS):
            b = QToolButton()
            b.setText(sym)
            b.setAutoRaise(True)
            b.setMinimumSize(32, 32)
            b.clicked.connect(lambda _=False, x=sym: self.symbol_edit.setText(x))
            grid.addWidget(b, i // 11, i % 11)

        image_btn = QPushButton("📷 Своя картинка…")
        image_btn.setAutoDefault(False)
        image_btn.setToolTip("Любая картинка - программа сама уменьшит её до размера значка")
        image_btn.clicked.connect(self.pick_image)
        self.clear_image_btn = QPushButton("Убрать картинку")
        self.clear_image_btn.setAutoDefault(False)
        self.clear_image_btn.clicked.connect(self.clear_image)
        reset_btn = QPushButton("↺ По умолчанию")
        reset_btn.setAutoDefault(False)
        reset_btn.clicked.connect(self.reset)

        form = QFormLayout()
        form.addRow("Цвет", color_btn)
        form.addRow("Символ", self.symbol_edit)
        form.addRow("", grid)
        img_row = QHBoxLayout()
        img_row.addWidget(image_btn)
        img_row.addWidget(self.clear_image_btn)
        img_row.addStretch(1)
        img_row.addWidget(reset_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(self.preview, 1)
        top.addWidget(self.preview_small)
        layout.addLayout(top)
        layout.addLayout(form)
        layout.addLayout(img_row)
        layout.addWidget(buttons)
        self.update_preview()

    def update_preview(self):
        self.preview.setPixmap(self.icons.badge_pixmap(self.tag, 96))
        self.preview_small.setPixmap(self.icons.badge_pixmap(self.tag, 46))
        self.preview_small.setToolTip("Так значок выглядит на обложке")
        self.clear_image_btn.setEnabled(bool(self.tag["icon_image"]))

    def on_symbol(self, text):
        self.tag["icon"] = text.strip()
        self.update_preview()

    def pick_color(self):
        color = QColorDialog.getColor(QColor(self.tag["color"]), self, "Цвет значка и тега")
        if color.isValid():
            self.tag["color"] = color.name()
            self.update_preview()

    def pick_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Картинка для значка", "", "Картинки (*.png *.jpg *.jpeg *.gif *.webp *.bmp *.ico *.svg)")
        if not path:
            return
        try:
            self.tag["icon_image"] = self.icons.import_icon_image(path, self.tag["id"])
        except ValueError as exc:
            QMessageBox.warning(self, "Значок", str(exc))
            return
        self.update_preview()

    def clear_image(self):
        self.tag["icon_image"] = ""
        self.update_preview()

    def reset(self):
        self.tag["icon_image"] = ""
        self.symbol_edit.setText(self.default_symbol)

    def apply(self):
        self.db.set_tag_color(self.tag["id"], self.tag["color"])
        self.db.set_tag_icon(self.tag["id"], self.tag["icon"])
        self.db.set_tag_icon_image(self.tag["id"], self.tag["icon_image"])


# ======================================================================
class RenameDialog(QDialog):
    """Переименование: один файл - просто новое имя, несколько - по шаблону. С предпросмотром."""

    def __init__(self, files, first_tags, parent=None):
        super().__init__(parent)
        from app import rename
        self.rename = rename
        self.files, self.first_tags = files, first_tags
        self.plan = []
        single = len(files) == 1
        self.setWindowTitle("Переименовать" if single else f"Переименовать файлы: {len(files)}")
        self.resize(760, 520 if not single else 300)

        stem = os.path.splitext(files[0]["name"])[0]
        self.pattern = QLineEdit(stem if single else "{имя}")
        self.pattern.textChanged.connect(self.update_plan)
        tokens = QHBoxLayout()
        for tok, tip in [("{имя}", "старое имя"), ("{n}", "номер по порядку"), ("{дата}", "дата изменения"),
                         ("{папка}", "имя папки"), ("{тег}", "первый твой тег")]:
            b = QToolButton()
            b.setText(tok)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, t=tok: self.pattern.insert(t))
            tokens.addWidget(b)
        tokens.addStretch(1)

        self.start = QSpinBox()
        self.start.setRange(0, 1_000_000)
        self.start.setValue(1)
        self.digits = QSpinBox()
        self.digits.setRange(1, 6)
        self.digits.setValue(2)
        self.find = QLineEdit()
        self.find.setPlaceholderText("что заменить")
        self.replace = QLineEdit()
        self.replace.setPlaceholderText("на что")
        self.case = QComboBox()
        self.case.addItems(list(rename.CASES))
        for w in (self.start, self.digits):
            w.valueChanged.connect(self.update_plan)
        for w in (self.find, self.replace):
            w.textChanged.connect(self.update_plan)
        self.case.currentIndexChanged.connect(self.update_plan)

        form = QFormLayout()
        form.addRow("Новое имя" if single else "Шаблон", self.pattern)
        if not single:
            form.addRow("", tokens)
            nums = QHBoxLayout()
            nums.addWidget(QLabel("{n} с"))
            nums.addWidget(self.start)
            nums.addWidget(QLabel("цифр"))
            nums.addWidget(self.digits)
            nums.addStretch(1)
            form.addRow("Счётчик", nums)
            fr = QHBoxLayout()
            fr.addWidget(self.find)
            fr.addWidget(QLabel("→"))
            fr.addWidget(self.replace)
            form.addRow("Заменить", fr)
            form.addRow("Регистр", self.case)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Было", "Станет"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.summary = QLabel("")
        info = QLabel("Расширения не меняются. Файлы переименовываются на диске, теги и оценки остаются. "
                      "Передумал - Ctrl+Z вернёт старые имена.")
        info.setWordWrap(True)
        info.setStyleSheet("color: #868e96;")

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Переименовать")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.summary)
        layout.addWidget(info)
        layout.addWidget(self.buttons)
        self.update_plan()
        self.pattern.setFocus()
        self.pattern.selectAll()

    def options(self):
        return self.rename.Options(
            pattern=self.pattern.text(), start=self.start.value(), digits=self.digits.value(),
            find=self.find.text(), replace=self.replace.text(), case=self.case.currentText())

    def update_plan(self):
        self.plan = self.rename.make_plan(self.files, self.options(), self.first_tags)
        self.table.setRowCount(len(self.plan))
        errors = changed = 0
        for row, it in enumerate(self.plan):
            old = QTableWidgetItem(os.path.basename(it.old_path))
            new = QTableWidgetItem(os.path.basename(it.new_path) + (f"   ⚠ {it.error}" if it.error else ""))
            if it.error:
                new.setForeground(QBrush(QColor("#ff6b6b")))
                errors += 1
            elif it.changed:
                new.setForeground(QBrush(QColor("#51cf66")))
                changed += 1
            self.table.setItem(row, 0, old)
            self.table.setItem(row, 1, new)
        ok = changed > 0 and errors == 0
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(ok)
        self.summary.setText(f"Изменится имён: {changed}" + (f"   ·   ошибок: {errors} - исправь шаблон" if errors else ""))


# ======================================================================
class StatsDialog(QDialog):
    """Статистика библиотеки: сколько, чего, где место, какие теги."""

    def __init__(self, st, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Статистика библиотеки")
        self.resize(720, 680)
        from html import escape

        def size(n):
            for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
                if n < 1024 or unit == "ТБ":
                    return f"{n:.0f} {unit}" if unit == "Б" else f"{n:.1f} {unit}"
                n /= 1024

        def bars(rows, value, label, color=lambda r: "#4c6ef5", fmt=str):
            if not rows:
                return "<p style='color:#868e96'>пока пусто</p>"
            top = max(value(r) for r in rows) or 1
            out = ["<table width='100%' cellspacing='0' cellpadding='3'>"]
            for r in rows:
                w = max(2, int(100 * value(r) / top))
                out.append(
                    f"<tr><td width='34%'>{label(r)}</td><td><table cellspacing='0' cellpadding='0' "
                    f"width='{w}%'><tr><td bgcolor='{color(r)}' height='12'></td></tr></table></td>"
                    f"<td width='18%' align='right'>{fmt(value(r))}</td></tr>")
            out.append("</table>")
            return "".join(out)

        tagged_pct = int(100 * st["tagged"] / st["files"]) if st["files"] else 0
        cards = [
            ("Файлов", f"{st['files']}"), ("Занимают", size(st["size"])),
            ("Своих тегов", f"{st['tags']}"), ("Размечено", f"{tagged_pct}%"),
            ("В избранном", f"{st['favorites']}"), ("С оценкой", f"{st['rated']}"),
            ("С заметкой", f"{st['noted']}"), ("Коллекций", f"{st['collections']}"),
            ("Потерянных", f"{st['missing']}"), ("Лишних копий", f"{st['dup_extra']} ({size(st['dup_wasted'])})"),
        ]
        card_html = "<table width='100%' cellspacing='6'><tr>" + "".join(
            f"<td align='center' style='border:1px solid #495057; padding:8px'>"
            f"<div style='font-size:18pt; font-weight:bold'>{v}</div><div style='color:#868e96'>{k}</div></td>"
            + ("</tr><tr>" if i == 4 else "") for i, (k, v) in enumerate(cards)) + "</tr></table>"

        html = (
            card_html
            + "<h3>Типы файлов - сколько места</h3>"
            + bars(st["by_type"], lambda r: r["size"], lambda r: f"{r['icon']} {escape(r['name'])} ({r['n']})",
                   lambda r: r["color"], size)
            + "<h3>Самые популярные теги</h3>"
            + bars(st["top_tags"], lambda r: r["n"], lambda r: escape(r["name"]), lambda r: r["color"])
            + "<h3>Добавлено по месяцам</h3>"
            + bars(st["by_month"], lambda r: r["n"], lambda r: r["month"] or "-")
            + "<h3>Самые большие файлы</h3>"
            + bars(st["biggest"], lambda r: r["size"], lambda r: escape(r["name"]), lambda r: "#f76707", size)
        )
        from PySide6.QtWidgets import QTextBrowser
        view = QTextBrowser()
        view.setHtml(html)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addWidget(view, 1)
        layout.addWidget(close)


# ======================================================================
class ShortcutsDialog(QDialog):
    def __init__(self, rows, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Горячие клавиши")
        self.resize(520, 560)
        table = QTableWidget(len(rows), 2)
        table.setHorizontalHeaderLabels(["Клавиши", "Что делает"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.setColumnWidth(0, 150)
        for r, (keys, desc) in enumerate(rows):
            k = QTableWidgetItem(keys.replace("Space", "Пробел").replace("Return", "Enter")
                                 .replace("Delete", "Del").replace("Escape", "Esc"))
            f = k.font()
            f.setBold(True)
            k.setFont(f)
            table.setItem(r, 0, k)
            table.setItem(r, 1, QTableWidgetItem(desc))
        hint = QLabel("В быстром просмотре: ← → листать, 1-5 оценка, Enter открыть, Пробел/Esc закрыть.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #868e96;")
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addWidget(table, 1)
        layout.addWidget(hint)
        layout.addWidget(close)
