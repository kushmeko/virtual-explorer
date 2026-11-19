"""Проверка обновлений через GitHub Releases.

Программа спрашивает у GitHub, какой релиз последний (api.github.com/repos/<репо>/releases/latest),
и сравнивает номер с текущей версией. Ничего не скачивает и не ставит сама - только сообщает и
открывает страницу релиза. Работает в фоне; без интернета или для закрытого репозитория молча
ничего не находит.
"""
import json
import re
import urllib.request

from app.version import GITHUB_REPO, VERSION

API = "https://api.github.com/repos/{repo}/releases/latest"


def parse_version(text):
    """'v1.5.2' / '1.5' / 'Версия 1.6.0-beta' -> (1, 5, 2) / (1, 5, 0) / (1, 6, 0). Не вышло - None."""
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", str(text or ""))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)


def is_newer(remote, current=VERSION):
    r, c = parse_version(remote), parse_version(current)
    return bool(r and c and r > c)


def parse_release(data):
    """Ответ GitHub -> {'version', 'tag', 'url', 'installer', 'notes'} или None."""
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag = data.get("tag_name") or ""
    if parse_version(tag) is None:
        return None
    installer = ""
    for asset in data.get("assets") or []:
        name = (asset.get("name") or "").lower()
        if name.endswith(".exe") and "setup" in name:
            installer = asset.get("browser_download_url") or ""
            break
    v = parse_version(tag)
    return {
        "version": f"{v[0]}.{v[1]}.{v[2]}",
        "tag": tag,
        "url": data.get("html_url") or "",
        "installer": installer,
        "notes": (data.get("body") or "").strip()[:2000],
    }


def fetch_latest(repo=GITHUB_REPO, timeout=5):
    """Последний релиз с GitHub или None (нет репо, нет интернета, нет релизов)."""
    if not repo:
        return None
    req = urllib.request.Request(API.format(repo=repo), headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"VirtualExplorer/{VERSION}",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - адрес фиксированный
            return parse_release(json.loads(resp.read().decode("utf-8")))
    except Exception:  # noqa: BLE001 - нет сети, 404, лимит запросов - просто «не знаем»
        return None


def check(repo=GITHUB_REPO, current=VERSION):
    """-> релиз, если он новее текущей версии, иначе None."""
    rel = fetch_latest(repo)
    return rel if rel and is_newer(rel["version"], current) else None
