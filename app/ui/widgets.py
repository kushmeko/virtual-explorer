"""Мелкие переиспользуемые виджеты: плашки-теги и раскладка "в строчку с переносом"."""
from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLayout, QPushButton, QToolButton, QWidget

EXCLUDE_COLOR = "#e03131"


class FlowLayout(QLayout):
    """Раскладывает виджеты слева направо и переносит на новую строку (как текст)."""

    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        x = rect.x() + m.left()
        y = rect.y() + m.top()
        right = rect.right() - m.right()
        line_height = 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > right and line_height > 0:
                x = rect.x() + m.left()
                y += line_height + self._spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + m.bottom()


def make_chip(text, color, checkable=False, checked=False):
    """Плашка-тег: полупрозрачная заливка, цветная рамка, при выборе - сплошная."""
    chip = QPushButton(text)
    chip.setCursor(Qt.PointingHandCursor)
    chip.setCheckable(checkable)
    chip.setChecked(checked)
    chip.setMinimumHeight(26)
    c = QColor(color)
    rgb = f"{c.red()},{c.green()},{c.blue()}"
    chip.setStyleSheet(
        f"""
        QPushButton {{
            background: rgba({rgb}, 45); color: {color};
            border: 1px solid {color}; border-radius: 13px; padding: 2px 12px;
        }}
        QPushButton:hover {{ background: rgba({rgb}, 100); }}
        QPushButton:checked {{ background: {color}; color: white; }}
        """
    )
    return chip


def make_filter_chip(text, color, state="off", icon=None):
    """Плашка в панели фильтра. state: off / include (нужен) / exclude (исключён).

    Как в магазине Steam: зелёная галочка - тег нужен, красный крест - исключён.
    """
    chip = QPushButton()
    chip.setCursor(Qt.PointingHandCursor)
    chip.setMinimumHeight(26)
    c = QColor(color)
    rgb = f"{c.red()},{c.green()},{c.blue()}"
    if state == "include":
        chip.setText("✓ " + text)
        style = f"background: {color}; color: white; border: 1px solid {color};"
        hover = f"background: {c.lighter(115).name()};"
    elif state == "exclude":
        chip.setText("✕ " + text)
        style = (f"background: rgba(224,49,49,40); color: {EXCLUDE_COLOR}; "
                 f"border: 1px dashed {EXCLUDE_COLOR}; text-decoration: line-through;")
        hover = "background: rgba(224,49,49,80);"
    else:
        chip.setText(text)
        style = f"background: rgba({rgb}, 45); color: {color}; border: 1px solid {color};"
        hover = f"background: rgba({rgb}, 100);"
    chip.setStyleSheet(
        f"QPushButton {{ {style} border-radius: 13px; padding: 2px 12px; }}"
        f"QPushButton:hover {{ {hover} }}"
    )
    if icon is not None:  # значок тега слева от названия
        chip.setIcon(icon)
        chip.setIconSize(QSize(18, 18))
    return chip


def make_group_label(text):
    """Подпись группы тегов в панели фильтра ("Тип файла:")."""
    label = QLabel(text)
    label.setStyleSheet("color: #868e96; font-weight: bold; padding: 4px 2px 0 6px;")
    return label


class TagChip(QFrame):
    """Плашка тега у файла: клик по названию - фильтр по тегу, ✕ - снять тег.

    partial=True - тег есть не у всех выделенных файлов (пунктирная рамка).
    """

    clicked = Signal()
    removed = Signal()

    def __init__(self, text, color, partial=False, parent=None, icon=None):
        super().__init__(parent)
        c = QColor(color)
        rgb = f"{c.red()},{c.green()},{c.blue()}"
        alpha = 20 if partial else 45
        border = "dashed" if partial else "solid"
        self.setObjectName("tagchip")
        self.setStyleSheet(
            f"#tagchip {{ background: rgba({rgb}, {alpha}); border: 1px {border} {color};"
            f" border-radius: 13px; }}"
            f"QPushButton, QToolButton {{ background: transparent; border: none; color: {color}; }}"
            f"QPushButton:hover {{ text-decoration: underline; }}"
            f"QToolButton:hover {{ color: {EXCLUDE_COLOR}; }}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 1, 4, 1)
        layout.setSpacing(2)
        name = QPushButton(text)
        if icon is not None:
            name.setIcon(icon)
            name.setIconSize(QSize(18, 18))
        name.setCursor(Qt.PointingHandCursor)
        name.setToolTip("Показать все файлы с этим тегом")
        name.clicked.connect(self.clicked)
        close = QToolButton()
        close.setText("✕")
        close.setCursor(Qt.PointingHandCursor)
        close.setToolTip("Снять тег")
        close.clicked.connect(self.removed)
        layout.addWidget(name)
        layout.addWidget(close)
        self.setMinimumHeight(26)


def clear_layout(layout):
    """Удаляет все виджеты из раскладки."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget() if item is not None else None
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()


class StarRating(QWidget):
    """Оценка 0…5 звёздами. Клик по уже выбранной звезде - снять оценку."""

    rated = Signal(int)

    def __init__(self, parent=None, size=20):
        super().__init__(parent)
        self.value = 0
        self._star_px = size
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.buttons = []
        for i in range(1, 6):
            b = QToolButton()
            b.setAutoRaise(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(f"Оценка {i}  (клавиша {i}; 0 - без оценки)")
            b.clicked.connect(lambda _=False, v=i: self.on_click(v))
            layout.addWidget(b)
            self.buttons.append(b)
        self.setRating(0)

    def on_click(self, v):
        v = 0 if v == self.value else v
        self.setRating(v)
        self.rated.emit(v)

    def setRating(self, v):
        self.value = int(v or 0)
        for i, b in enumerate(self.buttons, start=1):
            on = i <= self.value
            b.setText("★" if on else "☆")
            b.setStyleSheet(f"QToolButton {{ font-size: {self._star_px}px; border: none; padding: 0 1px;"
                            f" color: {'#fab005' if on else '#868e96'}; }}")
