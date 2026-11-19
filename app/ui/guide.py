"""Инструкция: показывается при первом запуске, снова - из «⚙ Настройки → Инструкция» или по F1."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout

PAGES = [
    ("👋", "Добро пожаловать!",
     "Виртуальный проводник раскладывает файлы <b>тегами и коллекциями</b> - как игры в библиотеке Steam. "
     "<br><br>Сами файлы <b>остаются на своих местах</b>: программа ничего не копирует и не перемещает, "
     "а только запоминает их и следит за изменениями.<br><br>Это займёт минуту - листай кнопкой «Далее»."),
    ("📂", "Библиотека и папки",
     "Нажми <b>«＋ Добавить»</b> (вверху слева или внизу окна) и выбери папку. Файлы появятся в библиотеке, "
     "а программа начнёт <b>следить за папкой</b>: новые файлы добавятся сами, перемещённые и переименованные - "
     "найдутся вместе с тегами.<br><br>Папки видны в боковой панели в разделе <b>«ПАПКИ»</b>. "
     "Правой кнопкой по папке можно убрать её из библиотеки.<br><br>"
     "🛟 Весь системный диск добавить нельзя - это защита от зависаний."),
    ("🏷", "Теги и значки",
     "Теги - цветные плашки. Поставить тег: выдели файл(ы) и впиши тег справа или нажми <b>Ctrl+T</b>.<br><br>"
     "Над файлами - <b>фильтр</b>: клик по плашке - <b>✓ нужен</b>, ещё клик - <b>✕ исключить</b>, ещё - убрать. "
     "«И / ИЛИ» - нужны все отмеченные теги или любой.<br><br>"
     "Теги можно <b>вкладывать</b> («Кошки» внутри «Животные»). У каждого тега есть <b>значок</b> - он виден "
     "на обложке. ПКМ по плашке → «Цвет и значок…»: свой символ или картинка."),
    ("📚", "Коллекции",
     "<b>Коллекция</b> - полка, куда кладёшь файлы сам: перетащи файлы мышкой на коллекцию в боковой панели.<br><br>"
     "<b>Динамическая коллекция ⚡</b> наполняется сама по правилам: теги, тип, размер, дата или поиск. "
     "Кнопка 💾 рядом с поиском сохраняет текущий поиск как динамическую коллекцию."),
    ("🔍", "Умный поиск",
     "Пиши как удобно: <b>кот</b>, <b>#Школа</b>, <b>-#Черновик</b>, <b>.pdf</b>, <b>размер>10мб</b>, "
     "<b>добавлен:7д</b>, <b>оценка>=4</b>, <b>цвет:синий</b>, <b>кот | пёс</b>.<br><br>"
     "Под строкой видно, как программа поняла запрос. Кнопка <b>?</b> - подсказки и история, "
     "<b>🎨</b> - поиск картинок по цвету. После <b>#</b> программа подсказывает теги."),
    ("⭐", "Файл: оценка, заметка, просмотр",
     "Справа - детали выделенного файла: <b>★ избранное</b>, <b>оценка 1-5</b> (или клавиши 1-5), "
     "теги, <b>заметка</b> и коллекции.<br><br>"
     "<b>Пробел</b> - быстрый просмотр: картинки, видео, музыка, PDF, текст. Стрелки листают файлы.<br>"
     "<b>Enter</b> - открыть файл, <b>F2</b> - переименовать (несколько файлов - по шаблону)."),
    ("🛡", "Ничего не потеряется",
     "<b>Ctrl+Z</b> отменяет любое действие, <b>Ctrl+Y</b> - повторяет.<br><br>"
     "Пропавшие с диска файлы попадают в <b>«⚠ Потерянные»</b> с тегами - вернёшь флешку, и всё на месте. "
     "Одинаковые файлы - в <b>«⧉ Дубликаты»</b>.<br><br>Резервные копии базы делаются сами каждый день."),
    ("⚙", "Настрой под себя",
     "В <b>«⚙ Настройки»</b> - темы и свои цвета, шрифт и размер текста, что показывать на обложках, "
     "свои <b>горячие клавиши</b> и параметры библиотеки.<br><br>"
     "Эту инструкцию можно открыть снова там же или клавишей <b>F1</b>.<br><br>Удачи с разбором файлов! 🎉"),
]


class GuideDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Как пользоваться")
        self.resize(620, 440)
        self.stack = QStackedWidget()
        for icon, title, body in PAGES:
            page = QLabel(f"<div style='font-size:42pt'>{icon}</div><h2>{title}</h2>"
                          f"<div style='font-size:11pt; line-height:140%'>{body}</div>")
            page.setWordWrap(True)
            page.setTextFormat(Qt.RichText)
            page.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            page.setMargin(18)
            self.stack.addWidget(page)
        self.counter = QLabel()
        self.counter.setStyleSheet("color: #8f98a0;")
        self.skip = QPushButton("Пропустить")
        self.back = QPushButton("◀ Назад")
        self.next = QPushButton("Далее ▶")
        self.next.setDefault(True)
        self.skip.clicked.connect(self.accept)
        self.back.clicked.connect(lambda: self.go(-1))
        self.next.clicked.connect(lambda: self.go(1))
        row = QHBoxLayout()
        row.addWidget(self.skip)
        row.addStretch(1)
        row.addWidget(self.counter)
        row.addStretch(1)
        row.addWidget(self.back)
        row.addWidget(self.next)
        layout = QVBoxLayout(self)
        layout.addWidget(self.stack, 1)
        layout.addLayout(row)
        self.update_buttons()

    def go(self, delta):
        i = self.stack.currentIndex() + delta
        if i >= self.stack.count():
            self.accept()
            return
        self.stack.setCurrentIndex(max(0, i))
        self.update_buttons()

    def update_buttons(self):
        i, n = self.stack.currentIndex(), self.stack.count()
        self.counter.setText(f"{i + 1} / {n}")
        self.back.setEnabled(i > 0)
        self.next.setText("Готово ✓" if i == n - 1 else "Далее ▶")
        self.skip.setVisible(i < n - 1)
