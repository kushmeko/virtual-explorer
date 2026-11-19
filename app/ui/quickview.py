"""Быстрый просмотр по пробелу - как Quick Look в macOS.

  Пробел / Esc   закрыть           ← →     предыдущий / следующий файл
  1…5, 0         поставить оценку  Enter   открыть в программе по умолчанию

Что показывает: картинки (GIF - с анимацией), текст и код, PDF, видео и музыку.
PDF и видео - если в установленном PySide6 есть модули QtPdf / QtMultimedia
(в обычном `pip install PySide6` они есть); иначе - карточка файла и кнопка «Открыть».
"""
import os

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QFont, QImageReader, QKeySequence, QMovie, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.ui.thumbs import placeholder_image
from app.ui.widgets import StarRating

TEXT_EXTS = {".txt", ".md", ".csv", ".json", ".log", ".ini", ".cfg", ".xml", ".yml", ".yaml",
             ".py", ".js", ".ts", ".html", ".css", ".c", ".cpp", ".h", ".cs", ".java", ".bat",
             ".ps1", ".sh", ".sql", ".srt", ".toml"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".ico", ".svg"}
VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv", ".m4v"}
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma"}
PDF_EXTS = {".pdf"}
TEXT_LIMIT = 300_000  # больше не читаем - просмотр должен открываться мгновенно

try:  # PDF
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPdfWidgets import QPdfView
except ImportError:  # pragma: no cover
    QPdfDocument = QPdfView = None

try:  # видео и звук
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QVideoWidget
except ImportError:  # pragma: no cover
    QMediaPlayer = QAudioOutput = QVideoWidget = None


def read_text(path):
    with open(path, "rb") as fh:
        raw = fh.read(TEXT_LIMIT + 1)
    cut = len(raw) > TEXT_LIMIT
    raw = raw[:TEXT_LIMIT]
    for enc in ("utf-8", "cp1251"):  # русские файлы из старых программ часто в cp1251
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    return text + ("\n\n… (показано начало файла)" if cut else "")


class QuickView(QDialog):
    def __init__(self, db, file_ids, index, on_rate=None, on_open=None, parent=None):
        super().__init__(parent)
        self.db, self.ids, self.index = db, list(file_ids), index
        self.on_rate, self.on_open = on_rate, on_open
        self.setWindowTitle("Быстрый просмотр")
        screen = self.screen().availableGeometry() if self.screen() else None
        if screen is not None:
            self.resize(int(screen.width() * 0.7), int(screen.height() * 0.8))
        else:
            self.resize(1100, 760)

        # шапка
        self.title = QLabel()
        f = QFont()
        f.setBold(True)
        f.setPointSize(f.pointSize() + 2)
        self.title.setFont(f)
        self.info = QLabel()
        self.info.setStyleSheet("color: #868e96;")
        self.stars = StarRating()
        self.stars.rated.connect(self.rate)
        self.counter = QLabel()
        self.counter.setStyleSheet("color: #868e96;")
        open_btn = QPushButton("Открыть  ⏎")
        open_btn.setFocusPolicy(Qt.NoFocus)
        open_btn.clicked.connect(self.open_current)
        head = QHBoxLayout()
        names = QVBoxLayout()
        names.addWidget(self.title)
        names.addWidget(self.info)
        head.addLayout(names, 1)
        head.addWidget(self.stars)
        head.addWidget(self.counter)
        head.addWidget(open_btn)

        # содержимое
        self.stack = QStackedWidget()
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setMinimumSize(200, 150)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setFocusPolicy(Qt.NoFocus)   # стрелки листают файлы, текст - колёсиком
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        self.text.setFont(mono)
        self.stack.addWidget(self.image)       # 0
        self.stack.addWidget(self.text)        # 1

        self.pdf_doc = self.pdf_view = None
        if QPdfView is not None:
            self.pdf_doc = QPdfDocument(self)
            self.pdf_view = QPdfView()
            self.pdf_view.setDocument(self.pdf_doc)
            self.pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
            self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
            self.pdf_view.setFocusPolicy(Qt.NoFocus)
            self.stack.addWidget(self.pdf_view)  # 2
        self.player = None
        if QMediaPlayer is not None:
            media = QWidget()
            ml = QVBoxLayout(media)
            self.video = QVideoWidget()
            self.audio_label = QLabel()
            self.audio_label.setAlignment(Qt.AlignCenter)
            self.player = QMediaPlayer(self)
            self.audio_out = QAudioOutput(self)
            self.player.setAudioOutput(self.audio_out)
            self.player.setVideoOutput(self.video)
            self.play_btn = QPushButton("⏸")
            self.play_btn.setFocusPolicy(Qt.NoFocus)
            self.play_btn.clicked.connect(self.toggle_play)
            self.seek = QSlider(Qt.Horizontal)
            self.seek.setFocusPolicy(Qt.NoFocus)
            self.seek.sliderMoved.connect(self.player.setPosition)
            self.player.durationChanged.connect(lambda d: self.seek.setRange(0, d))
            self.player.positionChanged.connect(
                lambda p: None if self.seek.isSliderDown() else self.seek.setValue(p))
            controls = QHBoxLayout()
            controls.addWidget(self.play_btn)
            controls.addWidget(self.seek, 1)
            ml.addWidget(self.video, 1)
            ml.addWidget(self.audio_label, 1)
            ml.addLayout(controls)
            self.media_page = media
            self.stack.addWidget(media)        # 3 (или 2, если нет PDF)
        self.movie = None

        hint = QLabel("Пробел/Esc - закрыть   ·   ← → - листать   ·   1…5 - оценка, 0 - без оценки"
                      "   ·   Enter - открыть")
        hint.setStyleSheet("color: #868e96;")
        hint.setAlignment(Qt.AlignCenter)

        layout = QVBoxLayout(self)
        layout.addLayout(head)
        layout.addWidget(self.stack, 1)
        layout.addWidget(hint)
        self.show_current()

    # ---------- показ ----------
    def current(self):
        return self.db.get_file(self.ids[self.index]) if self.ids else None

    def stop_media(self):
        if self.player is not None:
            self.player.stop()
            self.player.setSource(QUrl())
        if self.movie is not None:
            self.movie.stop()
            self.image.setMovie(None)
            self.movie = None
        if self.pdf_doc is not None:
            self.pdf_doc.close()

    def show_current(self):
        self.stop_media()
        f = self.current()
        if f is None:
            return
        self.title.setText(f["name"])
        size = f["size"]
        size_txt = f"{size / 1024 / 1024:.1f} МБ" if size > 1024 * 1024 else f"{size / 1024:.0f} КБ"
        self.info.setText(f"{size_txt}   ·   {f['path']}")
        self.stars.setRating(f["rating"] or 0)
        self.counter.setText(f"{self.index + 1} / {len(self.ids)}")
        path, ext = f["path"], f["ext"]
        if f["missing_since"] is not None or not os.path.exists(path):
            self.show_card(f, "⚠ Файла нет на диске")
        elif ext in IMAGE_EXTS:
            self.show_image(path, ext)
        elif ext in TEXT_EXTS:
            try:
                self.text.setPlainText(read_text(path))
                self.stack.setCurrentWidget(self.text)
            except OSError as exc:
                self.show_card(f, f"Не получилось прочитать: {exc}")
        elif ext in PDF_EXTS and self.pdf_doc is not None:
            self.pdf_doc.load(path)
            self.stack.setCurrentWidget(self.pdf_view)
        elif ext in VIDEO_EXTS | AUDIO_EXTS and self.player is not None:
            is_video = ext in VIDEO_EXTS
            self.video.setVisible(is_video)
            self.audio_label.setVisible(not is_video)
            if not is_video:
                self.audio_label.setPixmap(QPixmap.fromImage(placeholder_image(ext)))
            self.player.setSource(QUrl.fromLocalFile(path))
            self.player.play()
            self.play_btn.setText("⏸")
            self.stack.setCurrentWidget(self.media_page)
        else:
            self.show_card(f, "Для этого типа файла просмотра нет - нажми Enter, чтобы открыть")

    def show_image(self, path, ext):
        if ext == ".gif":
            self.movie = QMovie(path)
            if self.movie.isValid():
                size = QImageReader(path).size()   # кадр ещё не загружен - размер берём из файла
                if size.isValid():
                    self.movie.setScaledSize(self._fit(size))
                self.image.setMovie(self.movie)
                self.movie.start()
                self.stack.setCurrentWidget(self.image)
                return
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid():
            reader.setScaledSize(self._fit(size))
        img = reader.read()
        self.image.setPixmap(QPixmap.fromImage(img) if not img.isNull() else QPixmap())
        self.stack.setCurrentWidget(self.image)

    def _fit(self, size):
        area = self.stack.size() - QSize(20, 20)
        if area.width() < 100:
            area = QSize(1000, 650)
        if size.width() > area.width() or size.height() > area.height():
            size = size.scaled(area, Qt.KeepAspectRatio)
        return size

    def show_card(self, f, text):
        self.image.setPixmap(QPixmap.fromImage(placeholder_image(f["ext"])))
        self.image.setToolTip(text)
        self.info.setText(self.info.text() + "   ·   " + text)
        self.stack.setCurrentWidget(self.image)

    # ---------- действия ----------
    def toggle_play(self):
        if self.player is None:
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.play_btn.setText("▶")
        else:
            self.player.play()
            self.play_btn.setText("⏸")

    def step(self, delta):
        if not self.ids:
            return
        self.index = (self.index + delta) % len(self.ids)
        self.show_current()

    def rate(self, value):
        f = self.current()
        if f is not None and self.on_rate:
            self.on_rate(f["id"], value)
            self.stars.setRating(value)

    def open_current(self):
        f = self.current()
        if f is not None and self.on_open:
            self.on_open(f["path"])

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key_Space, Qt.Key_Escape):
            self.close()
        elif key == Qt.Key_Right or key == Qt.Key_Down:
            self.step(1)
        elif key == Qt.Key_Left or key == Qt.Key_Up:
            self.step(-1)
        elif key in (Qt.Key_Return, Qt.Key_Enter):
            self.open_current()
        elif int(Qt.Key_0) <= key <= int(Qt.Key_5):
            self.rate(key - int(Qt.Key_0))
        elif event.matches(QKeySequence.StandardKey.Copy):
            f = self.current()
            if f is not None:
                from PySide6.QtWidgets import QApplication  # noqa: PLC0415
                QApplication.clipboard().setText(f["path"])
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.stop_media()
        super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.stack.currentWidget() is self.image and self.movie is None and self.current():
            f = self.current()
            if f["ext"] in IMAGE_EXTS and os.path.exists(f["path"]):
                self.show_image(f["path"], f["ext"])
