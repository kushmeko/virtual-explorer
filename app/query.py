"""Умная строка поиска.

Пишешь как удобно - непонятное просто ищется как слово в имени файла и тегах.

    кот                 имя файла, тег или заметка содержит "кот"
    "летний отпуск"     фраза с пробелами
    #Школа  тег:Школа   есть тег Школа или любой вложенный в него
                        (#"два слова" - тег с пробелом)
    -#Черновик          НЕТ тега Черновик       (минус перед чем угодно = "не")
    .pdf  тип:pdf       расширение
    путь:Учёба          путь к файлу содержит
    размер>10мб         размер (б, кб, мб, гб; можно < и >)
    добавлен:7д         добавлен в библиотеку за последние 7 дней (д, н, м, г)
    изменён:30д         файл менялся за последние 30 дней
    ★  избранное        в избранном
    потерян             файла нет на диске
    дубликат            у файла есть копия с тем же содержимым
    оценка>=4           оценка (оценка:5, оценка<3)
    заметка:купить      текст в заметке
    цвет:синий          картинки, где много этого цвета
    кот | пёс           ИЛИ: части через | (или слово "или")
"""
import re
import time
from dataclasses import dataclass

TOKEN_RE = re.compile(r'-?[^\s:"]+:"[^"]*"|-?#"[^"]*"|-?"[^"]*"|\S+')

SIZE_UNITS = {"": 1, "б": 1, "b": 1, "кб": 1024, "kb": 1024, "к": 1024, "k": 1024,
              "мб": 1024 ** 2, "mb": 1024 ** 2, "м": 1024 ** 2, "m": 1024 ** 2,
              "гб": 1024 ** 3, "gb": 1024 ** 3, "г": 1024 ** 3, "g": 1024 ** 3}
DAY_UNITS = {"": 1, "д": 1, "d": 1, "н": 7, "w": 7, "м": 30, "m": 30, "г": 365, "y": 365}

KEYS = {
    "тег": "tag", "tag": "tag", "t": "tag",
    "тип": "ext", "ext": "ext", "type": "ext",
    "путь": "path", "path": "path", "папка": "path",
    "добавлен": "added", "added": "added",
    "заметка": "note", "note": "note",
    "цвет": "color", "color": "color",
    "изменён": "modified", "изменен": "modified", "modified": "modified",
}
WORD_FLAGS = {"★": "fav", "избранное": "fav", "fav": "fav",
              "потерян": "missing", "потерянные": "missing", "missing": "missing",
              "дубликат": "dups", "дубликаты": "dups", "копии": "dups", "dup": "dups"}
OR_WORDS = {"|", "или", "or"}


@dataclass
class Term:
    kind: str          # word, tag, ext, path, size, added, modified, fav, missing
    value: object = None
    op: str = ""       # для size: > или <
    neg: bool = False


def _unquote(s):
    return s[1:-1] if len(s) >= 2 and s[0] == s[-1] == '"' else s


def _num_unit(text, units):
    m = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*([a-zа-яё]*)", text.strip().lower())
    if not m or m.group(2) not in units:
        return None
    return float(m.group(1).replace(",", ".")) * units[m.group(2)]


def parse_term(tok):
    neg = tok.startswith("-") and len(tok) > 1
    body = tok[1:] if neg else tok
    low = body.lower()

    if low in WORD_FLAGS:
        return Term(WORD_FLAGS[low], neg=neg)
    if body.startswith("#") and len(body) > 1:
        return Term("tag", _unquote(body[1:]).lower(), neg=neg)
    if re.fullmatch(r"\.[\wа-яё]+", low):
        return Term("ext", low, neg=neg)

    m = re.fullmatch(r"(оценка|rating)\s*(>=|<=|[<>:=])\s*([0-5])", low)
    if m:
        op = "=" if m.group(2) in (":", "=") else m.group(2)
        return Term("rating", int(m.group(3)), op=op, neg=neg)

    m = re.fullmatch(r"(размер|size)\s*([<>])\s*(.+)", low)
    if m:
        n = _num_unit(m.group(3), SIZE_UNITS)
        if n is not None:
            return Term("size", int(n), op=m.group(2), neg=neg)

    if ":" in body:
        key, _, val = body.partition(":")
        kind = KEYS.get(key.lower())
        val = _unquote(val)
        if kind and val:
            if kind == "ext":
                return Term("ext", "." + val.lower().lstrip("."), neg=neg)
            if kind in ("added", "modified"):
                days = _num_unit(val, DAY_UNITS)
                if days is not None:
                    return Term(kind, days, neg=neg)
            else:
                return Term(kind, val.lower(), neg=neg)

    word = _unquote(body).lower()
    return Term("word", word, neg=neg) if word else None


def parse(text):
    """Строка -> список групп (ИЛИ), каждая группа - список условий (И)."""
    groups, current = [], []
    for tok in TOKEN_RE.findall(text or ""):
        if tok.lower() in OR_WORDS:
            if current:
                groups.append(current)
            current = []
            continue
        term = parse_term(tok)
        if term:
            current.append(term)
    if current:
        groups.append(current)
    return groups


def tag_tree_sql(seed_cond):
    """SELECT id тегов, подходящих под seed_cond, И всех их вложенных тегов (любой глубины).
    Так файл с тегом «Кошки» находится и по «Животные»."""
    return ("WITH RECURSIVE d(id) AS (SELECT id FROM tags WHERE " + seed_cond +
            " UNION SELECT c.id FROM tags c JOIN d ON c.parent_id = d.id) SELECT id FROM d")


def has_tag_sql(seed_cond):
    return ("EXISTS (SELECT 1 FROM file_tags x WHERE x.file_id = f.id AND x.tag_id IN ("
            + tag_tree_sql(seed_cond) + "))")


def term_sql(term):
    k, v = term.kind, term.value
    if k == "word":
        sql = ("(py_lower(f.name) LIKE ? OR py_lower(f.note) LIKE ? OR "
               + has_tag_sql("py_lower(name) LIKE ?") + ")")
        params = [f"%{v}%", f"%{v}%", f"%{v}%"]
    elif k == "tag":
        sql, params = has_tag_sql("py_lower(name) = ?"), [v]
    elif k == "ext":
        sql, params = "f.ext = ?", [v]
    elif k == "path":
        sql, params = "py_lower(f.path) LIKE ?", [f"%{v}%"]
    elif k == "size":
        sql, params = f"f.size {'>' if term.op == '>' else '<'} ?", [v]
    elif k == "added":
        sql, params = "f.added_at >= datetime('now', ?)", [f"-{v} days"]
    elif k == "modified":
        sql, params = "f.mtime >= ?", [time.time() - v * 86400]
    elif k == "fav":
        sql, params = "f.favorite = 1", []
    elif k == "missing":
        sql, params = "f.missing_since IS NOT NULL", []
    elif k == "rating":
        sql, params = f"f.rating {term.op} ?", [v]
    elif k == "note":
        sql, params = "py_lower(f.note) LIKE ?", [f"%{v}%"]
    elif k == "color":
        sql, params = "py_lower(f.colors) LIKE ?", [f"%{v}%"]
    elif k == "dups":
        from app.db import DUP_SQL  # noqa: PLC0415 - db импортирует query, избегаем круга
        sql, params = DUP_SQL, []
    else:
        return "1", []
    if term.neg:
        sql = f"NOT ({sql})"
    return sql, params


def to_sql(groups):
    """-> (sql, params) или ("", []) если условий нет."""
    parts, params = [], []
    for group in groups:
        conds = []
        for term in group:
            s, p = term_sql(term)
            conds.append(s)
            params.extend(p)
        parts.append("(" + " AND ".join(conds) + ")")
    if not parts:
        return "", []
    return "(" + " OR ".join(parts) + ")", params


def _fmt_size(n):
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024 or unit == "ГБ":
            return f"{n:.0f} {unit}" if unit == "Б" else f"{n:.1f} {unit}".replace(".0 ", " ")
        n /= 1024


def describe_term(t):
    k, v = t.kind, t.value
    text = {
        "word": lambda: f"«{v}» в имени или теге",
        "tag": lambda: f"тег {v}",
        "ext": lambda: f"тип {v}",
        "path": lambda: f"путь содержит «{v}»",
        "size": lambda: f"размер {'больше' if t.op == '>' else 'меньше'} {_fmt_size(v)}",
        "added": lambda: f"добавлен за {v:g} дн.",
        "modified": lambda: f"изменён за {v:g} дн.",
        "fav": lambda: "в избранном",
        "missing": lambda: "нет на диске",
        "dups": lambda: "есть копии",
        "rating": lambda: f"оценка {t.op} {v}".replace(">=", "≥").replace("<=", "≤"),
        "note": lambda: f"в заметке «{v}»",
        "color": lambda: f"цвет: {v}",
    }[k]()
    return ("не " + text) if t.neg else text


def describe(groups):
    """Человеческое пояснение: как программа поняла запрос."""
    if not groups:
        return ""
    return "  или  ".join(" · ".join(describe_term(t) for t in g) for g in groups)


def is_simple(groups):
    """Обычный текст без подсказок - пояснение не нужно."""
    return len(groups) == 1 and all(t.kind == "word" and not t.neg for t in groups[0]) \
        and len(groups[0]) == 1
