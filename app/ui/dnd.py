"""Перетаскивание файлов мышкой на боковую панель (как игры на коллекцию в Steam).

  * FileGrid / FileTable - сетка и таблица, из которых можно тащить выделенные файлы
  * SidebarTree          - сайдбар, который принимает файлы:
        обычная коллекция      -> файлы кладутся в неё
        ★ Избранное            -> файлы в избранное
        заголовок "КОЛЛЕКЦИИ"  -> новая коллекция из этих файлов
        динамическая коллекция -> нельзя (она наполняется по правилам), курсор "запрещено"

В перетаскивании едут только id файлов из базы, а не сами файлы:
бросить их в проводник Windows или на рабочий стол нельзя, и файлы на диске не сдвинутся.
"""
import json

from PySide6.QtCore import QMimeData, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QDrag, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QTableWidget, QTreeWidget

MIME = "application/x-virtual-explorer-file-ids"

# что сайдбар принимает: вид пункта -> подсказка в строке состояния
DROP_TARGETS = {
    "static": "Отпусти - файлы попадут в коллекцию «{name}»",
    "fav": "Отпусти - файлы попадут в Избранное",
    "new_static": "Отпусти - будет создана новая коллекция из этих файлов",
}
DROP_REFUSED = {
    "dynamic": "Динамическая коллекция наполняется сама по правилам - файлы в неё не кладут",
}


def encode_ids(ids):
    mime = QMimeData()
    mime.setData(MIME, json.dumps(list(ids)).encode("utf-8"))
    return mime


def decode_ids(mime):
    if not mime.hasFormat(MIME):
        return []
    try:
        return [int(i) for i in json.loads(bytes(mime.data(MIME)).decode("utf-8"))]
    except (ValueError, TypeError):
        return []


def drag_pixmap(base, count):
    """Картинка под курсором: обложка первого файла + кружок с числом файлов."""
    w, h = 120, 90
    pix = QPixmap(w + 14, h + 14)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    if count > 1:  # "стопка" карточек
        p.setBrush(QColor(80, 85, 95, 200))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRect(8, 8, w, h), 6, 6)
    p.setOpacity(0.9)
    if base is not None and not base.isNull():
        p.drawPixmap(QRect(0, 0, w, h), base.scaled(w, h, Qt.KeepAspectRatioByExpanding,
                                                     Qt.SmoothTransformation))
    else:
        p.setBrush(QColor("#4a4f57"))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRect(0, 0, w, h), 6, 6)
    p.setOpacity(1.0)
    if count > 1:
        p.setBrush(QColor("#1c7ed6"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRect(w - 22, h - 22, 34, 34))
        font = QFont()
        font.setBold(True)
        font.setPixelSize(15)
        p.setFont(font)
        p.setPen(Qt.white)
        p.drawText(QRect(w - 22, h - 22, 34, 34), Qt.AlignCenter, str(count))
    p.end()
    return pix


def _start_drag(view, ids, base):
    if not ids:
        return
    drag = QDrag(view)
    drag.setMimeData(encode_ids(ids))
    pix = drag_pixmap(base, len(ids))
    drag.setPixmap(pix)
    drag.setHotSpot(QPoint(pix.width() // 2, pix.height() // 2))
    drag.exec(Qt.CopyAction)


class FileGrid(QListWidget):
    resized = Signal()   # размер окна поменялся - главное окно догрузит видимые обложки

    def __init__(self, ids_provider, parent=None):
        super().__init__(parent)
        self.ids_provider = ids_provider

    def enable_drag(self):
        """Звать ПОСЛЕ setViewMode/setMovement: они сами переключают режим перетаскивания."""
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit()

    def startDrag(self, _actions):
        ids = self.ids_provider()
        item = self.currentItem() or (self.selectedItems() or [None])[0]
        base = item.icon().pixmap(self.iconSize()) if item is not None else None
        _start_drag(self, ids, base)


class FileTable(QTableWidget):
    def __init__(self, ids_provider, rows, cols, parent=None):
        super().__init__(rows, cols, parent)
        self.ids_provider = ids_provider
        self.cover_provider = None  # функция id -> QPixmap, задаёт главное окно
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)

    def startDrag(self, _actions):
        ids = self.ids_provider()
        base = self.cover_provider(ids[0]) if ids and self.cover_provider else None
        _start_drag(self, ids, base)


class SidebarTree(QTreeWidget):
    """filesDropped(вид пункта, id пункта, [id файлов])."""

    filesDropped = Signal(str, int, list)
    hint = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DropOnly)
        self._highlighted = None

    # --- что под курсором ---
    def _target(self, pos):
        item = self.itemAt(pos)
        if item is None:
            return None, None
        kind = item.data(0, Qt.UserRole + 3) or item.data(0, Qt.UserRole)
        return item, kind

    def _highlight(self, item):
        if self._highlighted is item:
            return
        if self._highlighted is not None:
            try:
                self._highlighted.setBackground(0, QBrush())
            except RuntimeError:  # пункт уже удалён при обновлении сайдбара
                pass
        self._highlighted = item
        if item is not None:
            self._highlighted.setBackground(0, QBrush(QColor(28, 126, 214, 90)))

    # --- события перетаскивания ---
    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if not event.mimeData().hasFormat(MIME):
            event.ignore()
            return
        item, kind = self._target(event.position().toPoint())
        if kind in DROP_TARGETS:
            self._highlight(item)
            name = item.data(0, Qt.UserRole + 2) or ""
            self.hint.emit(DROP_TARGETS[kind].format(name=name))
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            self._highlight(None)
            self.hint.emit(DROP_REFUSED.get(kind, ""))
            event.ignore()

    def dragLeaveEvent(self, event):
        self._highlight(None)
        self.hint.emit("")
        event.accept()

    def dropEvent(self, event):
        item, kind = self._target(event.position().toPoint())
        self._highlight(None)
        self.hint.emit("")
        ids = decode_ids(event.mimeData())
        if kind not in DROP_TARGETS or not ids:
            event.ignore()
            return
        event.setDropAction(Qt.CopyAction)
        event.accept()
        ident = item.data(0, Qt.UserRole + 1) or 0
        self.filesDropped.emit(kind, int(ident), ids)
