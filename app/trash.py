"""Отправка файлов в Корзину Windows (их можно вернуть оттуда).

Программа сама файлы не трогает - это единственное исключение, и только по явной
команде пользователя с подтверждением: убрать лишние копии-дубликаты.
Если установлен пакет send2trash - используем его, иначе вызываем Windows напрямую.
"""
import os
import sys


def available():
    if sys.platform == "win32":
        return True
    try:
        import send2trash  # noqa: F401, PLC0415
        return True
    except ImportError:
        return False


def _windows_recycle(path):
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    class SHFILEOPSTRUCTW(ctypes.Structure):
        if ctypes.sizeof(ctypes.c_void_p) == 4:  # в 32-битной Windows структура упакована
            _pack_ = 1
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", ctypes.c_wchar_p),
            ("pTo", ctypes.c_wchar_p),
            ("fFlags", ctypes.c_ushort),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", ctypes.c_wchar_p),
        ]

    FO_DELETE = 3
    FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 0x4, 0x10, 0x40, 0x400
    # список путей должен заканчиваться ДВУМЯ нулевыми символами
    buf = ctypes.create_unicode_buffer(os.path.abspath(path) + "\0")
    op = SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    op.pFrom = ctypes.cast(buf, ctypes.c_wchar_p)
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if result != 0 or op.fAnyOperationsAborted:
        raise OSError(f"Windows не смогла отправить файл в Корзину (код {result})")


def to_trash(path):
    """Отправляет файл в Корзину. Бросает OSError, если не вышло."""
    if not os.path.exists(path):
        raise OSError("Файла уже нет на диске")
    try:
        from send2trash import send2trash  # noqa: PLC0415
        send2trash(path)
        return
    except ImportError:
        pass
    if sys.platform == "win32":
        _windows_recycle(path)
    else:
        raise OSError("Корзина доступна только в Windows (или с пакетом send2trash)")
