# Рецепт сборки для PyInstaller:  pyinstaller packaging/virtual_explorer.spec --noconfirm
# Результат - папка dist/VirtualExplorer с VirtualExplorer.exe (режим «папка», а не «один файл»:
# так программа быстрее запускается и антивирусы реже ругаются на неё по ошибке).
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821 - SPECPATH задаёт PyInstaller

# неиспользуемые части Qt - без них сборка меньше в несколько раз
EXCLUDES = [
    "tkinter", "unittest", "pydoc", "test",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets", "PySide6.QtWebView",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtLocation",
    "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtSerialBus", "PySide6.QtRemoteObjects",
    "PySide6.QtScxml", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp",
    "PySide6.QtOpenGLWidgets", "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech",
    "PySide6.QtHttpServer", "PySide6.QtStateMachine",
]

a = Analysis(  # noqa: F821
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    datas=[
        (os.path.join(ROOT, "app", "fonts"), os.path.join("app", "fonts")),
        (os.path.join(ROOT, "app", "assets"), os.path.join("app", "assets")),
    ],
    hiddenimports=[
        "PySide6.QtNetwork", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
        "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    ],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VirtualExplorer",
    icon=os.path.join(ROOT, "packaging", "icon.ico"),
    version=os.path.join(ROOT, "packaging", "version_info.txt"),
    console=False,          # без чёрного окна консоли
    upx=False,              # UPX-сжатие часто даёт ложные срабатывания антивирусов
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    upx=False,
    name="VirtualExplorer",
)
