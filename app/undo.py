"""Отмена и повтор действий (Ctrl+Z / Ctrl+Y).

Перед каждым действием пользователя база целиком копируется в память - это быстро
(SQLite backup, миллисекунды) и надёжно: отменяется ЛЮБОЕ действие с тегами, коллекциями,
оценками, заметками - без отдельного кода отмены для каждой кнопки.
Действия с файлами на диске (пакетное переименование) несут свои функции отмены/повтора.
"""
import sqlite3
from dataclasses import dataclass, field

LIMIT = 30
MEMORY_BUDGET = 300 * 1024 * 1024   # на все копии вместе - даже у огромной библиотеки не съест память


def db_size(conn):
    page_count = conn.execute("PRAGMA page_count").fetchone()[0]
    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    return page_count * page_size


@dataclass
class Step:
    label: str
    snapshot: sqlite3.Connection
    fs_undo: object = None     # функция: откатить изменения на диске
    fs_redo: object = None
    extra: dict = field(default_factory=dict)


def _snapshot(conn):
    conn.commit()
    mem = sqlite3.connect(":memory:")
    conn.backup(mem)
    return mem


def _restore(conn, mem):
    conn.commit()
    mem.backup(conn)


class UndoStack:
    def __init__(self, conn, limit=LIMIT):
        self.conn = conn
        self.limit = limit
        self.undo_steps = []
        self.redo_steps = []

    def checkpoint(self, label, fs_undo=None, fs_redo=None):
        """Звать ПЕРЕД изменением. Новое действие обнуляет «повтор»."""
        self.undo_steps.append(Step(label, _snapshot(self.conn), fs_undo, fs_redo))
        while len(self.undo_steps) > self.max_steps():
            self.undo_steps.pop(0).snapshot.close()
        for st in self.redo_steps:
            st.snapshot.close()
        self.redo_steps.clear()

    def max_steps(self):
        """Сколько шагов держать: 30, но меньше, если база большая (не больше MEMORY_BUDGET)."""
        size = max(db_size(self.conn), 1)
        return max(1, min(self.limit, MEMORY_BUDGET // size))

    def set_fs(self, fs_undo, fs_redo):
        """Привязать к последнему шагу отмену действий на диске (когда они уже сделаны)."""
        if self.undo_steps:
            self.undo_steps[-1].fs_undo, self.undo_steps[-1].fs_redo = fs_undo, fs_redo

    def drop_last(self):
        """Действие не состоялось (отменили диалог) - убрать лишний шаг."""
        if self.undo_steps:
            self.undo_steps.pop().snapshot.close()

    def can_undo(self):
        return bool(self.undo_steps)

    def can_redo(self):
        return bool(self.redo_steps)

    def undo_label(self):
        return self.undo_steps[-1].label if self.undo_steps else ""

    def redo_label(self):
        return self.redo_steps[-1].label if self.redo_steps else ""

    def undo(self):
        if not self.undo_steps:
            return None
        step = self.undo_steps.pop()
        if step.fs_undo:
            step.fs_undo()          # сначала диск: если не вышло - база не трогается
        current = _snapshot(self.conn)
        _restore(self.conn, step.snapshot)
        step.snapshot.close()
        self.redo_steps.append(Step(step.label, current, step.fs_undo, step.fs_redo))
        return step.label

    def redo(self):
        if not self.redo_steps:
            return None
        step = self.redo_steps.pop()
        if step.fs_redo:
            step.fs_redo()
        current = _snapshot(self.conn)
        _restore(self.conn, step.snapshot)
        step.snapshot.close()
        self.undo_steps.append(Step(step.label, current, step.fs_undo, step.fs_redo))
        return step.label
