"""Подготовка к сборке (запускается на GitHub перед PyInstaller).

    python packaging/stamp_version.py <владелец/репозиторий> <версия или тег>

* записывает версию и адрес репозитория в app/version.py - по ним программа проверяет обновления;
* создаёт packaging/version_info.txt - «Свойства → Подробно» у VirtualExplorer.exe;
* отдаёт версию следующим шагам сборки (переменная VER в GITHUB_ENV).
Если версия не передана (пусто), берётся та, что уже записана в app/version.py.
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_PY = ROOT / "app" / "version.py"
INFO = ROOT / "packaging" / "version_info.txt"

TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(filevers=({a}, {b}, {c}, 0), prodvers=({a}, {b}, {c}, 0),
                    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041904B0', [
      StringStruct('CompanyName', 'Virtual Explorer'),
      StringStruct('FileDescription', 'Виртуальный проводник'),
      StringStruct('FileVersion', '{v}'),
      StringStruct('InternalName', 'VirtualExplorer'),
      StringStruct('OriginalFilename', 'VirtualExplorer.exe'),
      StringStruct('ProductName', 'Виртуальный проводник'),
      StringStruct('ProductVersion', '{v}')])]),
    VarFileInfo([VarStruct('Translation', [1049, 1200])])
  ]
)
"""


def parse(text):
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)) if m else None


def main():
    repo = sys.argv[1] if len(sys.argv) > 1 else ""
    wanted = sys.argv[2] if len(sys.argv) > 2 else ""
    src = VERSION_PY.read_text(encoding="utf-8")
    current = re.search(r'^VERSION = "([^"]+)"', src, re.M).group(1)
    ver = parse(wanted) or parse(current)
    if ver is None:
        sys.exit(f"Не понял номер версии: {wanted!r}")
    v = "{}.{}.{}".format(*ver)
    src = re.sub(r'^VERSION = "[^"]*"', f'VERSION = "{v}"', src, flags=re.M)
    if re.fullmatch(r"[\w.-]+/[\w.-]+", repo or ""):
        src = re.sub(r'^GITHUB_REPO = "[^"]*"', f'GITHUB_REPO = "{repo}"', src, flags=re.M)
    VERSION_PY.write_text(src, encoding="utf-8")
    INFO.write_text(TEMPLATE.format(a=ver[0], b=ver[1], c=ver[2], v=v), encoding="utf-8")
    env = os.environ.get("GITHUB_ENV")
    if env:
        with open(env, "a", encoding="utf-8") as f:
            f.write(f"VER={v}\n")
    print(f"Версия {v}, репозиторий {repo or '(не задан)'}")


if __name__ == "__main__":
    main()
