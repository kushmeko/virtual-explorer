"""Обучение при первом запуске: затемнение, подсвеченная кнопка и стрелка к ней.

Каждый шаг - (как найти виджет, заголовок, текст). Окно-подсказка встаёт рядом с виджетом
(снизу, сверху, справа или слева - где есть место), а стрелка ведёт от подсказки к нему.
Esc - закрыть, Enter / → - дальше, ← - назад. Шаги с невидимым виджетом пропускаются.
"""
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

PAD = 8          # отступ подсветки вокруг виджета
BUBBLE_W = 340


class Tour(QWidget):
    finished = Signal()

    def __init__(self, window, steps, accent="#66c0f4"):
        super().__init__(window)
        self.win = window
        self.steps = steps
        self.accent = QColor(accent)
        self.index = 0
        self.target_rect = QRect()
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setFocusPolicy(Qt.StrongFocus)

        self.bubble = QFrame(self)
        self.bubble.setObjectName("tourBubble")
        self.bubble.setStyleSheet(
            f"#tourBubble {{ background: #ffffff; border-radius: 12px; border: 2px solid {self.accent.name()}; }}"
            "#tourBubble QLabel { color: #1b2838; background: transparent; }"
            "#tourBubble QPushButton { background: #eef2f6; color: #1b2838; border: 1px solid #cfd6dd;"
            " border-radius: 6px; padding: 5px 12px; }"
            f"#tourBubble QPushButton#next {{ background: {self.accent.name()}; color: white; border: none;"
            " font-weight: bold; }")
        self.bubble.setFixedWidth(BUBBLE_W)
        self.title = QLabel()
        self.title.setStyleSheet("font-size: 13pt; font-weight: bold;")
        self.title.setWordWrap(True)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.RichText)
        self.counter = QLabel()
        self.counter.setStyleSheet("color: #8f98a0;")
        self.skip_btn = QPushButton("Пропустить")
        self.back_btn = QPushButton("◀")
        self.next_btn = QPushButton("Далее ▶")
        self.next_btn.setObjectName("next")
        self.skip_btn.clicked.connect(self.finish)
        self.back_btn.clicked.connect(lambda: self.go(-1))
        self.next_btn.clicked.connect(lambda: self.go(1))
        row = QHBoxLayout()
        row.addWidget(self.skip_btn)
        row.addStretch(1)
        row.addWidget(self.counter)
        row.addWidget(self.back_btn)
        row.addWidget(self.next_btn)
        lay = QVBoxLayout(self.bubble)
        lay.setContentsMargins(16, 14, 16, 12)
        lay.addWidget(self.title)
        lay.addWidget(self.text)
        lay.addSpacing(6)
        lay.addLayout(row)

        window.installEventFilter(self)
        self.setGeometry(window.rect())

    # ---------- жизненный цикл ----------
    def start(self):
        self.show()
        self.raise_()
        self.setFocus()
        self.show_step()

    def finish(self):
        self.win.removeEventFilter(self)
        self.hide()
        self.deleteLater()
        self.finished.emit()

    def eventFilter(self, obj, event):
        if obj is self.win and event.type() in (QEvent.Resize, QEvent.Move, QEvent.Show):
            self.setGeometry(self.win.rect())
            self.show_step(keep=True)
        return False

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Escape:
            self.finish()
        elif key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Right, Qt.Key_Space):
            self.go(1)
        elif key == Qt.Key_Left:
            self.go(-1)

    def mousePressEvent(self, event):
        event.accept()   # клики мимо подсказки не уходят в программу

    # ---------- шаги ----------
    def visible_target(self, i):
        get = self.steps[i][0]
        w = get() if get else None
        if w is None:
            return None, True
        if not w.isVisible():
            return None, False
        top_left = w.mapTo(self.win, QPoint(0, 0))
        return QRect(top_left, w.size()), True

    def go(self, delta):
        i = self.index + delta
        while 0 <= i < len(self.steps):
            _rect, ok = self.visible_target(i)
            if ok:
                break
            i += delta          # шаг с невидимой кнопкой (например, панель спрятана) - пропускаем
        if i >= len(self.steps):
            self.finish()
            return
        self.index = max(0, i)
        self.show_step()

    def show_step(self, keep=False):
        if not self.steps:
            return
        rect, _ok = self.visible_target(self.index)
        self.target_rect = rect.adjusted(-PAD, -PAD, PAD, PAD) if rect is not None else QRect()
        _get, title, text = self.steps[self.index]
        self.title.setText(title)
        self.text.setText(text)
        n = len(self.steps)
        self.counter.setText(f"{self.index + 1}/{n}")
        self.back_btn.setEnabled(self.index > 0)
        self.next_btn.setText("Готово ✓" if self.index == n - 1 else "Далее ▶")
        self.skip_btn.setVisible(self.index < n - 1)
        self.bubble.adjustSize()
        self.place_bubble()
        self.update()

    def place_bubble(self):
        area = self.rect()
        bw, bh = self.bubble.width(), self.bubble.sizeHint().height()
        t = self.target_rect
        gap = 46   # место под стрелку
        if t.isNull():   # без цели - по центру
            x, y = (area.width() - bw) // 2, (area.height() - bh) // 2
        elif t.bottom() + gap + bh < area.height():           # снизу
            x, y = t.center().x() - bw // 2, t.bottom() + gap
        elif t.top() - gap - bh > 0:                          # сверху
            x, y = t.center().x() - bw // 2, t.top() - gap - bh
        elif t.right() + gap + bw < area.width():             # справа
            x, y = t.right() + gap, t.center().y() - bh // 2
        else:                                                 # слева
            x, y = t.left() - gap - bw, t.center().y() - bh // 2
        x = max(12, min(x, area.width() - bw - 12))
        y = max(12, min(y, area.height() - bh - 12))
        self.bubble.setGeometry(x, y, bw, bh)

    # ---------- рисование ----------
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        shade = QPainterPath()
        shade.addRect(QRectF(self.rect()))
        t = self.target_rect
        if not t.isNull():
            hole = QPainterPath()
            hole.addRoundedRect(QRectF(t), 10, 10)
            shade = shade.subtracted(hole)
        p.fillPath(shade, QColor(0, 0, 0, 165))
        if t.isNull():
            return
        pen = QPen(self.accent, 3)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(t), 10, 10)
        # стрелка: от края подсказки к краю подсветки
        b = self.bubble.geometry()
        start = QPointF(min(max(t.center().x(), b.left() + 20), b.right() - 20),
                        b.top() if b.top() > t.bottom() else b.bottom())
        if b.left() > t.right():
            start = QPointF(b.left(), min(max(t.center().y(), b.top() + 20), b.bottom() - 20))
        elif b.right() < t.left():
            start = QPointF(b.right(), min(max(t.center().y(), b.top() + 20), b.bottom() - 20))
        end = QPointF(min(max(start.x(), t.left() + 6), t.right() - 6),
                      min(max(start.y(), t.top() + 6), t.bottom() - 6))
        if b.top() > t.bottom():
            end.setY(t.bottom() + 2)
        elif b.bottom() < t.top():
            end.setY(t.top() - 2)
        elif b.left() > t.right():
            end.setX(t.right() + 2)
        elif b.right() < t.left():
            end.setX(t.left() - 2)
        p.setPen(QPen(self.accent, 3, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(start, end)
        # наконечник
        dx, dy = end.x() - start.x(), end.y() - start.y()
        length = max((dx * dx + dy * dy) ** 0.5, 1)
        ux, uy = dx / length, dy / length
        size = 13
        left = QPointF(end.x() - ux * size - uy * size * 0.6, end.y() - uy * size + ux * size * 0.6)
        right = QPointF(end.x() - ux * size + uy * size * 0.6, end.y() - uy * size - ux * size * 0.6)
        p.setBrush(self.accent)
        p.setPen(Qt.NoPen)
        p.drawPolygon(QPolygonF([end, left, right]))
