"""Настройки программы - всё, что пользователь может подстроить под себя.

Хранятся в базе (таблица settings) одним словарём "app_settings". Чего нет - берётся
из DEFAULTS, так что новые настройки в новых версиях появляются сами.
"""
import copy

DEFAULTS = {
    # --- внешний вид ---
    "theme": "steam",           # steam | dark | light | system | custom | saved:<имя>
    "custom_colors": {},        # цвета «своей темы» (см. theme.COLOR_ROLES)
    "custom_themes": {},        # сохранённые свои темы: {имя: цвета}
    "font_family": "",          # '' - системный, 'inter' - вшитый Inter, иначе имя шрифта
    "font_pt": 0,               # размер текста в пунктах, 0 - как в системе
    "ui_scale": 100,            # масштаб всего интерфейса, % (применяется при запуске)
    "text_color": "",           # свой цвет текста ('' - из темы)
    "density": "normal",        # compact | normal | comfortable - отступы в списках
    "language": "ru",           # пока только русский
    "cover_badges": 3,          # сколько значков тегов на обложке (0 - не показывать)
    "cover_stars": True,        # звёзды оценки на обложке
    "cover_strip": True,        # цветная полоска тегов внизу обложки
    "show_details": True,       # правая панель с деталями файла
    # --- библиотека ---
    "page_size": 1000,          # сколько файлов показывать за раз
    "start_view": "last",       # all | last - что открывать при запуске
    "watch_folders": True,      # следить за изменениями в папках
    "auto_duplicates": True,    # искать дубликаты в фоне
    "auto_colors": True,        # считать цвета картинок в фоне
    "big_folder_files": 50000,  # после стольких файлов спрашивать при добавлении
    "confirm_remove": True,     # спрашивать перед «Убрать из библиотеки»
    # --- обновления ---
    "check_updates": True,      # раз в день спрашивать GitHub, нет ли новой версии
    "update_checked": 0,        # когда проверяли (время, секунды)
    "skip_version": "",         # «пропустить эту версию»
    # --- служебное ---
    "onboarding_done": False,   # показана ли инструкция при первом запуске
    "shortcuts": {},            # свои горячие клавиши: {id действия: "Ctrl+…"}
    "window": {},               # размер окна, раскладка, режим, сортировка, размер обложек
    "settings_version": 3,
}

UI_SCALES = [80, 90, 100, 110, 125, 150, 175]
DENSITY = {"compact": "Компактно", "normal": "Обычно", "comfortable": "Просторно"}
LANGUAGES = {"ru": "Русский"}
KEY = "app_settings"


class Settings:
    def __init__(self, db):
        self.db = db
        stored = db.get_setting(KEY, {}) or {}
        # с прошлых версий тема хранилась отдельно
        if "theme" not in stored and db.get_setting("theme"):
            stored["theme"] = db.get_setting("theme")
        self.data = copy.deepcopy(DEFAULTS)
        self.data.update(stored)
        if stored and int(stored.get("settings_version", 1)) < 2:
            # до v1.3 «тёмная» тема была в цветах Steam - теперь это отдельная заготовка
            if self.data.get("theme") == "dark":
                self.data["theme"] = "steam"
            self.data["settings_version"] = 2
        if stored and int(stored.get("settings_version", 1)) < 3:
            # v1.4: шрифт «как в Steam» убран - возвращаем системный
            if self.data.get("font_family") == "steam":
                self.data["font_family"] = ""
            self.data["settings_version"] = 3

    def __getitem__(self, key):
        return self.data.get(key, DEFAULTS.get(key))

    def get(self, key, default=None):
        return self.data.get(key, DEFAULTS.get(key, default))

    def set(self, key, value, save=True):
        self.data[key] = value
        if save:
            self.save()

    def update(self, values):
        self.data.update(values)
        self.save()

    def save(self):
        self.db.set_setting(KEY, self.data)

    def reset(self, keys=None):
        """Вернуть по умолчанию (всё или перечисленные ключи), кроме служебных."""
        keep = {"onboarding_done", "window"}
        for k in (keys or DEFAULTS):
            if k not in keep or keys:
                self.data[k] = copy.deepcopy(DEFAULTS[k])
        self.save()
