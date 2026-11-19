"""Только одна запущенная копия программы.

Если программу открыть второй раз (двойной клик по ярлыку, запуск после установки), новая
копия не запускается, а показывает уже открытое окно. Раньше вторая копия видела метку
«программа работает» и ошибочно предлагала безопасный режим, а две копии писали в одну базу.
Работает через QLocalServer (именованный канал Windows).
"""
import getpass

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def _server_name():
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = "user"
    return "VirtualExplorer-" + "".join(c for c in user if c.isalnum())[:40]


class SingleInstance(QObject):
    activate = Signal()   # кто-то запустил программу ещё раз - покажи окно

    def __init__(self, parent=None):
        super().__init__(parent)
        self.name = _server_name()
        self.server = None

    def already_running(self):
        """True - копия уже запущена (ей отправлен сигнал «покажись»), этой копии надо выйти."""
        sock = QLocalSocket()
        sock.connectToServer(self.name)
        if sock.waitForConnected(400):
            sock.write(b"show")
            sock.flush()
            sock.waitForBytesWritten(400)
            sock.disconnectFromServer()
            return True
        # никто не ответил: занимаем имя (старое могло остаться после падения)
        QLocalServer.removeServer(self.name)
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._on_connection)
        self.server.listen(self.name)
        return False

    def _on_connection(self):
        while self.server.hasPendingConnections():
            conn = self.server.nextPendingConnection()
            conn.readyRead.connect(conn.readAll)
            conn.disconnected.connect(conn.deleteLater)
        self.activate.emit()
