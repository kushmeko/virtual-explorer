"""Обложки файлов в стиле библиотеки Steam.

* картинки - настоящие превью, грузятся В ФОНЕ и кэшируются на диск (папка thumbs_cache в папке программы)
* остальные файлы - нарисованная карточка с расширением, цвет по типу файла
* поверх обложки: ★ у избранного, цветная полоска тегов и значки тегов (до 3 + «…»)
"""
import hashlib
from pathlib import Path

from PySide6.QtCore import QObject, QRect, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QImageReader,
    QLinearGradient,
    QPainter,
    QPixmap,
)

from app.db import AUTO_TAGS, EXT_TO_AUTO
from app.paths import thumbs_dir

COVER_W, COVER_H = 320, 240
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}

try:  # обложки PDF - первая страница (модуль QtPdf входит в обычный PySide6)
    from PySide6.QtPdf import QPdfDocument
    PDF_COVERS = True
except ImportError:  # pragma: no cover
    QPdfDocument = None
    PDF_COVERS = False

# у каких файлов рисуем настоящую обложку (остальным - карточка с расширением)
PREVIEW_EXTS = IMAGE_EXTS | ({".pdf"} if PDF_COVERS else set())
CACHE_DIR = thumbs_dir()  # в папке программы, не рядом с файлами пользователя

_placeholders = {}


def make_cover_image(path):
    """Превью картинки COVER_W x COVER_H (обрезка по центру). None, если не вышло."""
    try:
        st = Path(path).stat()
    except OSError:
        return None
    key = hashlib.sha1(f"{path}|{st.st_mtime_ns}|{st.st_size}".encode("utf-8")).hexdigest()
    cache_file = CACHE_DIR / f"{key}.png"
    if cache_file.exists():
        cached = QImage(str(cache_file))
        if not cached.isNull():
            return cached

    if path.lower().endswith(".pdf"):
        img = _pdf_first_page(path)
        if img is None:
            return None
        return _finish_cover(img, cache_file)

    reader = QImageReader(path)
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and size.width() > 0 and size.height() > 0:
        scale = max(COVER_W / size.width(), COVER_H / size.height())
        if scale < 1:  # читаем сразу уменьшенной - быстрее и меньше памяти
            reader.setScaledSize(QSize(int(size.width() * scale) + 1, int(size.height() * scale) + 1))
    img = reader.read()
    if img.isNull():
        return None
    return _finish_cover(img, cache_file)


def _pdf_first_page(path):
    if QPdfDocument is None:
        return None
    doc = QPdfDocument()
    try:
        doc.load(path)
        if doc.pageCount() < 1:
            return None
        page = doc.pagePointSize(0)
        if page.width() <= 0:
            return None
        scale = COVER_W / page.width()
        img = doc.render(0, QSize(COVER_W, max(1, int(page.height() * scale))))
        if img.isNull():
            return None
        # белый фон под страницей (у некоторых PDF он прозрачный)
        out = QImage(img.size(), QImage.Format_ARGB32_Premultiplied)
        out.fill(QColor("white"))
        p = QPainter(out)
        p.drawImage(0, 0, img)
        p.end()
        return out
    finally:
        doc.close()


def _finish_cover(img, cache_file):
    """Обрезка по центру до COVER_W×COVER_H (PDF - по верху страницы) и кэш на диск."""
    top_align = img.height() > img.width() * 1.2   # страница документа - показываем начало
    img = img.scaled(COVER_W, COVER_H, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    y = 0 if top_align else (img.height() - COVER_H) // 2
    img = img.copy((img.width() - COVER_W) // 2, y, COVER_W, COVER_H)
    try:
        CACHE_DIR.mkdir(exist_ok=True)
        img.save(str(cache_file), "PNG")
    except Exception:
        pass
    return img


def placeholder_image(ext, loading=False):
    """Карточка-заглушка: цвет по типу файла, крупно расширение."""
    key = (ext, loading)
    if key in _placeholders:
        return _placeholders[key]
    category = EXT_TO_AUTO.get(ext)
    color = QColor(AUTO_TAGS[category][0] if category else "#5c6370")
    if loading:
        color = QColor("#4a4f57")

    img = QImage(COVER_W, COVER_H, QImage.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    grad = QLinearGradient(0, 0, COVER_W, COVER_H)
    grad.setColorAt(0, color.darker(160))
    grad.setColorAt(1, color.darker(280))
    p.fillRect(img.rect(), QBrush(grad))

    font = QFont()
    font.setBold(True)
    font.setPixelSize(64)
    p.setFont(font)
    p.setPen(QColor(255, 255, 255, 235))
    label = "…" if loading else (ext.lstrip(".").upper()[:5] or "FILE")
    p.drawText(QRect(0, 0, COVER_W, COVER_H - 30), Qt.AlignCenter, label)
    if category and not loading:
        font.setPixelSize(22)
        font.setBold(False)
        p.setFont(font)
        p.setPen(QColor(255, 255, 255, 150))
        p.drawText(QRect(0, COVER_H - 56, COVER_W, 36), Qt.AlignCenter, category)
    p.end()
    _placeholders[key] = img
    return img


def compose_cover(base, favorite, tag_colors, missing=False, badges=(), hidden=0, rating=0):
    """Накладывает на обложку ★ (избранное) и полоску цветов тегов. Возвращает QPixmap.

    missing=True - файла нет на диске: обложка серая и тёмная, плашка "⚠ Нет на диске"
    (как не установленная игра в библиотеке Steam).
    """
    img = base.convertToFormat(QImage.Format_ARGB32_Premultiplied)
    if missing:
        img = img.convertToFormat(QImage.Format_Grayscale8).convertToFormat(
            QImage.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    if missing:
        p.fillRect(img.rect(), QColor(0, 0, 0, 120))
        p.fillRect(0, COVER_H // 2 - 26, COVER_W, 52, QColor(201, 42, 42, 220))
        font = QFont()
        font.setBold(True)
        font.setPixelSize(26)
        p.setFont(font)
        p.setPen(QColor("white"))
        p.drawText(QRect(0, COVER_H // 2 - 26, COVER_W, 52), Qt.AlignCenter, "⚠ Нет на диске")
    colors = tag_colors[:6]
    if colors:
        seg = COVER_W // len(colors)
        for i, c in enumerate(colors):
            p.fillRect(i * seg, COVER_H - 9, seg if i < len(colors) - 1 else COVER_W - i * seg, 9, QColor(c))
    if rating:  # оценка - звёзды в левом нижнем углу
        font = QFont()
        font.setPixelSize(24)
        p.setFont(font)
        text = "★" * rating
        w = p.fontMetrics().horizontalAdvance(text) + 14
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 150))
        p.drawRoundedRect(8, COVER_H - 9 - 8 - 34, w, 34, 8, 8)
        p.setPen(QColor("#fab005"))
        p.drawText(QRect(8, COVER_H - 9 - 8 - 34, w, 34), Qt.AlignCenter, text)
    if badges:  # значки тегов в правом нижнем углу: до 3 + «…»
        from app.ui.icons import badge_pixmap, more_pixmap  # noqa: PLC0415
        size, gap = 46, 6
        x = COVER_W - 10 - size
        y = COVER_H - 9 - 8 - size
        if hidden:
            p.drawPixmap(x, y, more_pixmap(size, hidden))
            x -= size + gap
        for tag in reversed(list(badges)):
            p.drawPixmap(x, y, badge_pixmap(tag, size))
            x -= size + gap
    if favorite:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 150))
        p.drawEllipse(COVER_W - 50, 10, 40, 40)
        font = QFont()
        font.setBold(True)
        font.setPixelSize(28)
        p.setFont(font)
        p.setPen(QColor("#ffd43b"))
        p.drawText(QRect(COVER_W - 50, 10, 40, 40), Qt.AlignCenter, "★")
    p.end()
    return QPixmap.fromImage(img)


# ---------- фоновая загрузка ----------
class _Signals(QObject):
    done = Signal(int, QImage)


class _Job(QRunnable):
    def __init__(self, file_id, path, signals):
        super().__init__()
        self.file_id = file_id
        self.path = path
        self.signals = signals

    def run(self):
        img = make_cover_image(self.path)
        if img is not None:
            self.signals.done.emit(self.file_id, img)


class ThumbnailLoader(QObject):
    """Грузит превью в нескольких потоках; готовые приходят сигналом loaded(id, QImage)."""

    loaded = Signal(int, QImage)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(4)
        self._signals = _Signals()
        self._signals.done.connect(self.loaded)
        self._requested = set()

    def request(self, file_id, path):
        if file_id in self._requested:
            return
        self._requested.add(file_id)
        self.pool.start(_Job(file_id, path, self._signals))

    def reset(self):
        """Сбросить очередь: ещё не начатые загрузки отменяются (уже идущие доделаются)."""
        self.pool.clear()
        self._requested.clear()

    def shutdown(self):
        self.pool.clear()
        self.pool.waitForDone(2000)


# ---------- главные цвета картинок (для поиска «цвет:синий») ----------
def image_colors(path):
    """Читает картинку уменьшенной до 32×32 и возвращает "синий,белый". Можно в фоне."""
    from app.colors import dominant  # noqa: PLC0415
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    reader.setScaledSize(QSize(32, 32))
    img = reader.read()
    if img.isNull():
        return ""
    img = img.convertToFormat(QImage.Format_ARGB32)
    px = []
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            px.append((c.red(), c.green(), c.blue(), c.alpha()))
    return dominant(px)


def compute_colors(rows):
    """rows: [(id, путь)] -> {id: "цвета"} ('' - не вышло или ярких цветов нет)."""
    result = {}
    for fid, path in rows:
        try:
            result[fid] = image_colors(path)
        except Exception:  # noqa: BLE001 - битая картинка не должна останавливать остальные
            result[fid] = ""
    return result
