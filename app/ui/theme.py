"""Оформление программы.

Темы:
  * «Тёмная (как в Steam)» - заготовка в цветах библиотеки Steam
  * «Тёмная» - обычная нейтральная тёмная
  * «Светлая» и «Как в системе»
  * «Своя тема» - пользователь сам задаёт каждый цвет (COLOR_ROLES) и может сохранить
    её под своим именем; сохранённые темы появляются в списке рядом с заготовками.
Текст: шрифт (системный, вшитый Inter или любой установленный),
размер и свой цвет текста. Основа - стиль Fusion + палитра + таблица стилей (QSS).
"""
import glob
import os

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette

STEAM = {
    "bg": "#1b2838", "panel": "#171d25", "panel2": "#202d39", "field": "#2a3f5a",
    "text": "#c7d5e0", "muted": "#8f98a0", "accent": "#66c0f4", "accent_bg": "#2a6a96",
    "hover": "#2f4a63", "border": "#2f3d4c", "sel_text": "#ffffff",
}
DARK = {
    "bg": "#1e1f22", "panel": "#18191c", "panel2": "#26282c", "field": "#2f3136",
    "text": "#e3e5e8", "muted": "#9a9ea6", "accent": "#7aa2f7", "accent_bg": "#3b4a6b",
    "hover": "#33363c", "border": "#3a3d43", "sel_text": "#ffffff",
}
LIGHT = {
    "bg": "#f4f6f8", "panel": "#e9edf1", "panel2": "#ffffff", "field": "#ffffff",
    "text": "#1f2933", "muted": "#66727f", "accent": "#1c7ed6", "accent_bg": "#cfe5fb",
    "hover": "#dde7f0", "border": "#cfd6dd", "sel_text": "#0b2540",
}
PRESETS = {"steam": ("Тёмная (как в Steam)", STEAM), "dark": ("Тёмная", DARK), "light": ("Светлая", LIGHT)}

# цвета «своей темы»: ключ, название, где виден
COLOR_ROLES = [
    ("bg", "Фон окна", "основной фон, область с файлами"),
    ("panel", "Панели", "боковая панель, верхняя панель, строка состояния"),
    ("panel2", "Карточки и списки", "сетка файлов, меню, карточки настроек"),
    ("field", "Поля ввода", "поиск, выпадающие списки, заметка"),
    ("text", "Текст", "основной текст"),
    ("muted", "Второстепенный текст", "подсказки, счётчики, заголовки разделов"),
    ("accent", "Акцент", "рамка в фокусе, ссылки, ползунки"),
    ("accent_bg", "Выделение", "выбранный файл, раздел, главная кнопка"),
    ("sel_text", "Текст на выделении", "текст поверх выделения"),
    ("hover", "Наведение", "подсветка под мышкой"),
    ("border", "Рамки", "границы панелей и полей"),
]

PADDING = {"compact": 2, "normal": 4, "comfortable": 7}
BUNDLED_FONT = "inter"

QSS = """
QMainWindow, QDialog {{ background: {bg}; color: {text}; }}
QWidget {{ color: {text}; }}
QToolBar {{ background: {panel}; border: none; border-bottom: 1px solid {border}; padding: 2px 6px; spacing: 2px; }}
QToolBar QToolButton {{ padding: 4px 8px; border-radius: 6px; }}
QToolBar QToolButton#primary {{ background: {accent_bg}; color: {sel_text}; font-weight: bold; padding: 4px 12px; }}
QToolBar QToolButton#primary:hover {{ background: {accent}; }}
QToolButton#viewToggle {{ border: 1px solid {border}; border-radius: 6px; padding: 4px 8px; }}
QToolButton#viewToggle:hover {{ border-color: {accent}; }}
QToolBar QToolButton:hover {{ background: {hover}; }}
QToolBar QToolButton:disabled {{ color: {muted}; }}
QTreeWidget {{ background: {panel}; border: none; padding-top: 6px; outline: 0; }}
QTreeWidget::item {{ padding: {pad}px 6px; border-radius: 4px; }}
QTreeWidget::item:hover {{ background: {hover}; }}
QTreeWidget::item:selected {{ background: {accent_bg}; color: {sel_text}; }}
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextBrowser {{
    background: {field}; border: 1px solid {border}; border-radius: 6px; padding: 5px 8px;
    selection-background-color: {accent_bg}; }}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{ border: 1px solid {accent}; }}
QComboBox QAbstractItemView {{ background: {panel2}; selection-background-color: {accent_bg}; }}
QPushButton {{ background: {panel2}; border: 1px solid {border}; border-radius: 6px; padding: 6px 12px; }}
QPushButton:hover {{ background: {hover}; border-color: {accent}; }}
QPushButton:pressed {{ background: {accent_bg}; }}
QPushButton:checked {{ background: {accent_bg}; border-color: {accent}; }}
QPushButton:disabled {{ color: {muted}; }}
QListView, QListWidget, QTableWidget, QTableView {{
    background: {panel2}; alternate-background-color: {bg}; border: 1px solid {border};
    border-radius: 8px; outline: 0; }}
QListView::item {{ border-radius: 8px; }}
QTableView::item {{ padding: {pad}px 4px; }}
QListView::item:hover {{ background: {hover}; }}
QListView::item:selected, QTableView::item:selected {{ background: {accent_bg}; color: {sel_text}; }}
QHeaderView::section {{ background: {panel}; color: {muted}; border: none;
    border-bottom: 1px solid {border}; padding: 6px; }}
QMenu {{ background: {panel2}; border: 1px solid {border}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px 6px 14px; border-radius: 4px; }}
QMenu::item:selected {{ background: {accent_bg}; color: {sel_text}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 8px; }}
QStatusBar {{ background: {panel}; color: {muted}; border-top: 1px solid {border}; }}
QSplitter::handle {{ background: {border}; width: 1px; }}
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {hover}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {accent_bg}; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {hover}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QToolTip {{ background: {panel2}; color: {text}; border: 1px solid {border}; padding: 6px; }}
QProgressBar {{ background: {field}; border: 1px solid {border}; border-radius: 6px; text-align: center; }}
QProgressBar::chunk {{ background: {accent_bg}; border-radius: 6px; }}
QSlider::groove:horizontal {{ height: 4px; background: {border}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {accent}; width: 14px; margin: -6px 0; border-radius: 7px; }}
QLabel#sectionTitle {{ color: {muted}; font-weight: bold; }}
QListWidget#settingsNav {{ background: {panel}; border: none; border-radius: 0; padding: 8px 4px; }}
QListWidget#settingsNav::item {{ padding: 10px 12px; border-radius: 6px; margin: 1px 4px; }}
QListWidget#settingsNav::item:selected {{ background: {accent_bg}; color: {sel_text}; }}
QListWidget#settingsNav::item:hover {{ background: {hover}; }}
QFrame#card {{ background: {panel2}; border: 1px solid {border}; border-radius: 10px; }}
QLabel#cardTitle {{ color: {muted}; font-weight: bold; letter-spacing: 1px; }}
QLabel#rowTitle {{ font-weight: 600; }}
QFrame#rowLine {{ background: {border}; max-height: 1px; border: none; }}
QKeySequenceEdit QLineEdit, QLineEdit#keyEdit {{ padding: 2px 8px; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QPushButton#swatch {{ border: 2px solid {border}; border-radius: 6px; padding: 0; }}
QPushButton#swatch:hover {{ border-color: {accent}; }}
QLabel#panelTitle {{ font-size: {title_pt}pt; font-weight: bold; }}
QLabel#muted {{ color: {muted}; }}
QPushButton#addButton {{ background: transparent; border: none; color: {muted}; padding: 2px 8px; }}
QPushButton#addButton:hover {{ color: {accent}; }}
"""


def theme_choices(settings):
    """[(ключ, название)] для списка тем: заготовки, сохранённые, «Своя тема»."""
    items = [(k, label) for k, (label, _c) in PRESETS.items()]
    items.append(("system", "Как в системе"))
    for name in sorted((settings.get("custom_themes") or {}), key=str.lower):
        items.append((f"saved:{name}", f"★ {name}"))
    items.append(("custom", "Своя тема (настроить цвета)"))
    return items


def colors_for(key, settings):
    """Цвета темы по ключу; None - «как в системе»."""
    if key in PRESETS:
        return dict(PRESETS[key][1])
    if key == "system":
        return None
    if key.startswith("saved:"):
        saved = (settings.get("custom_themes") or {}).get(key[6:])
        if saved:
            return {**STEAM, **saved}
        return dict(STEAM)
    if key == "custom":
        return {**STEAM, **(settings.get("custom_colors") or {})}
    return dict(STEAM)


FONTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts")
_bundled = {}


def bundled_font():
    """Inter - бесплатный шрифт (лицензия OFL), вшит в программу: app/fonts. -> семейство или None."""
    if "family" in _bundled:
        return _bundled["family"]
    family = None
    for f in sorted(glob.glob(os.path.join(FONTS_DIR, "*.otf")) + glob.glob(os.path.join(FONTS_DIR, "*.ttf"))):
        fid = QFontDatabase.addApplicationFont(f)
        fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
        if fams and family is None:
            family = fams[0]
    _bundled["family"] = family
    return family


def resolve_font_family(choice):
    """'' - системный, 'inter' - вшитый Inter (или Segoe UI, если файлов нет), иначе - имя шрифта."""
    if not choice or choice == "steam":   # «как в Steam» убран в v1.4
        return None
    if choice == BUNDLED_FONT:
        return bundled_font() or "Segoe UI"
    return choice


def _palette(c):
    pal = QPalette()
    roles = {
        QPalette.Window: c["bg"], QPalette.WindowText: c["text"], QPalette.Base: c["panel2"],
        QPalette.AlternateBase: c["bg"], QPalette.Text: c["text"], QPalette.Button: c["panel2"],
        QPalette.ButtonText: c["text"], QPalette.Highlight: c["accent_bg"],
        QPalette.HighlightedText: c["sel_text"], QPalette.ToolTipBase: c["panel2"],
        QPalette.ToolTipText: c["text"], QPalette.PlaceholderText: c["muted"], QPalette.Link: c["accent"],
    }
    for role, color in roles.items():
        pal.setColor(role, QColor(color))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(c["muted"]))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(c["muted"]))
    pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor(c["muted"]))
    return pal


_original = {}


def apply_theme(app, settings):
    """Применяет тему, шрифт, размер и цвет текста из настроек (dict или Settings)."""
    if "style" not in _original:
        _original["style"] = app.style().objectName()
        _original["palette"] = QPalette(app.palette())
        _original["font"] = QFont(app.font())
    font = QFont(_original["font"])
    family = resolve_font_family(settings.get("font_family") or "")
    if family:
        font.setFamily(family)
    pt = int(settings.get("font_pt") or 0)
    if pt > 0:
        font.setPointSize(max(7, min(24, pt)))
    app.setFont(font)

    colors = colors_for(settings.get("theme") or "steam", settings)
    if colors is None:   # как в системе
        app.setStyleSheet("")
        app.setStyle(_original["style"])
        app.setPalette(_original["palette"])
        return
    text_color = settings.get("text_color") or ""
    if text_color and QColor(text_color).isValid():
        colors["text"] = QColor(text_color).name()
    colors["pad"] = PADDING.get(settings.get("density") or "normal", 4)
    size = font.pointSizeF() if font.pointSizeF() > 0 else 9
    colors["title_pt"] = round(size * 1.45)
    app.setStyle("Fusion")
    app.setPalette(_palette(colors))
    app.setStyleSheet(QSS.format(**colors))
