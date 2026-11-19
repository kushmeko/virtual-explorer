"""Значки тегов.

Значок - кружок цвета тега, в нём символ (эмодзи или буква) или своя картинка.
  * авто-теги: 🖼 Картинки, 📄 Документы, 🎬 Видео … (можно поменять цвет, символ, картинку)
  * свои теги: по умолчанию первая буква названия; можно любой символ или свою картинку
Своя картинка любого размера сама уменьшается до ICON_STORE×ICON_STORE и хранится
в папке программы (tag_icons), а не рядом с файлами пользователя.
На обложке в правом нижнем углу - до MAX_BADGES значков, остальные - «…».
"""
import os
import time

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QImageReader, QPainter, QPainterPath, QPixmap

from app.paths import data_dir

ICON_STORE = 128      # своя картинка хранится в таком размере (с запасом для чёткости)
MAX_BADGES = 3
QUICK_SYMBOLS = list("🖼📄📊📽🎬🎵🗜💻⭐❤🔥✅📌📁🏠🎓💼🎮🐱🐶🌿✈🍔💰🔒🎨📷📚🧪⚽🎁🚗")

_cache = {}


def icons_dir():
    d = data_dir() / "tag_icons"
    d.mkdir(parents=True, exist_ok=True)
    return d


def import_icon_image(src_path, tag_id):
    """Берёт любую картинку, уменьшает (с сохранением пропорций, по центру) и сохраняет PNG.
    Возвращает имя файла или бросает ValueError."""
    reader = QImageReader(src_path)
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and max(size.width(), size.height()) > 2048:
        size.scale(2048, 2048, Qt.KeepAspectRatio)   # огромные картинки читаем сразу уменьшенными
        reader.setScaledSize(size)
    img = reader.read()
    if img.isNull():
        raise ValueError(f"Не получилось прочитать картинку: {reader.errorString()}")
    img = img.scaled(ICON_STORE, ICON_STORE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    out = QImage(ICON_STORE, ICON_STORE, QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.drawImage((ICON_STORE - img.width()) // 2, (ICON_STORE - img.height()) // 2, img)
    p.end()
    name = f"tag{tag_id}_{int(time.time())}.png"
    if not out.save(str(icons_dir() / name), "PNG"):
        raise ValueError("Не получилось сохранить значок")
    return name


def icon_symbol(tag):
    """Что рисовать в кружке: выбранный символ или первая буква названия."""
    sym = (tag["icon"] or "").strip()
    return sym if sym else (tag["name"][:1].upper() or "?")


def badge_pixmap(tag, size=40):
    """Круглый значок тега. tag - строка базы (id, name, color, icon, icon_image)."""
    key = (tag["id"], tag["color"], tag["icon"], tag["icon_image"], tag["name"][:1], size)
    pix = _cache.get(key)
    if pix is not None:
        return pix
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    circle = QPainterPath()
    circle.addEllipse(QRectF(1, 1, size - 2, size - 2))
    p.fillPath(circle, QColor(tag["color"]))
    custom = tag["icon_image"]
    path = str(icons_dir() / custom) if custom else ""
    if custom and os.path.exists(path):
        p.setClipPath(circle)
        p.drawImage(QRect(1, 1, size - 2, size - 2), QImage(path))
        p.setClipping(False)
    else:
        font = QFont()
        font.setBold(True)
        font.setPixelSize(int(size * 0.55))
        p.setFont(font)
        p.setPen(QColor("white"))
        p.drawText(QRect(0, 0, size, size), Qt.AlignCenter, icon_symbol(tag))
    p.setPen(QColor(255, 255, 255, 200))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QRectF(1, 1, size - 2, size - 2))   # светлая обводка - видно на любой обложке
    p.end()
    pix = QPixmap.fromImage(img)
    if len(_cache) > 2000:
        _cache.clear()
    _cache[key] = pix
    return pix


def more_pixmap(size=40, hidden=0):
    key = ("more", size, hidden)
    if key not in _cache:
        img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(40, 44, 52, 220))
        p.setPen(QColor(255, 255, 255, 200))
        p.drawEllipse(QRectF(1, 1, size - 2, size - 2))
        font = QFont()
        font.setBold(True)
        font.setPixelSize(int(size * 0.42))
        p.setFont(font)
        p.setPen(QColor("white"))
        p.drawText(QRect(0, -size // 10, size, size), Qt.AlignCenter, "…")
        p.end()
        _cache[key] = QPixmap.fromImage(img)
    return _cache[key]


def badge_icon(tag, size=18):
    return QIcon(badge_pixmap(tag, size * 2))   # вдвое больше - чётко на экранах с масштабом


def order_badges(tag_ids, tags_map, limit=MAX_BADGES):
    """Порядок значков на обложке: сначала тип файла (авто-тег), потом свои теги
    (самые популярные первыми). -> (первые limit тегов, сколько спрятано в «…»).
    limit=0 - значки не показываются совсем (настройка «Значков тегов на обложке»)."""
    if limit <= 0:
        return [], 0
    tags = [tags_map[t] for t in tag_ids if t in tags_map]
    tags.sort(key=lambda t: (0 if t["is_auto"] else 1, -t["cnt"], t["name"].lower()))
    return tags[:limit], max(0, len(tags) - limit)


def badges_key(shown, hidden):
    return tuple((t["id"], t["color"], t["icon"], t["icon_image"]) for t in shown) + (hidden,)
