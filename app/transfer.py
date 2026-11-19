"""Экспорт и импорт тегов в открытый JSON - данные не заперты в программе.

Eagle хранит всё в своём формате, «понятном только Eagle»; у Tabbles «нельзя выгрузить
список тегов». Здесь - обычный читаемый файл:
{
  "format": "virtual-explorer", "version": 1,
  "tags":  [{"name": "Кошки", "color": "#e8590c", "group": "", "parent": "Животные"}],
  "collections": [{"name": "Полка", "dynamic": false} | {"name": "...", "dynamic": true, "rules": {...}}],
  "files": [{"path": "C:\\\\...\\\\a.jpg", "name": "a.jpg", "size": 123,
             "tags": ["Школа"], "favorite": true, "collections": ["Полка"]}]
}
В правилах динамических коллекций id тегов заменены на имена, чтобы файл читался где угодно.
Импорт ДОБАВЛЯЕТ теги/коллекции/★ (ничего не снимает). Файл ищется по пути,
а если путь другой (другой компьютер, другая буква диска) - по имени и размеру.
"""
import json
import os
from dataclasses import dataclass

FORMAT = "virtual-explorer"


def export_json(db, path):
    tags = db.get_tags_with_counts()
    tag_name = {t["id"]: t["name"] for t in tags}
    cols = db.get_collections()
    col_name = {c["id"]: c["name"] for c in cols}

    file_tags, file_cols = {}, {}
    for r in db.conn.execute("SELECT file_id, tag_id FROM file_tags"):
        file_tags.setdefault(r["file_id"], []).append(tag_name[r["tag_id"]])
    for r in db.conn.execute("SELECT file_id, collection_id FROM file_collections"):
        file_cols.setdefault(r["file_id"], []).append(col_name[r["collection_id"]])

    def rules_out(rules):
        out = dict(rules)
        for key in ("tags", "exclude_tags"):
            if key in out:
                out[key] = [tag_name[t] for t in out[key] if t in tag_name]
        return out

    data = {
        "format": FORMAT,
        "version": 1,
        "tags": [{"name": t["name"], "color": t["color"], "group": t["grp"],
                  "auto": bool(t["is_auto"]), "parent": tag_name.get(t["parent_id"]),
                  "icon": t["icon"]}
                 for t in tags],
        "collections": [
            {"name": c["name"], "dynamic": c["rules"] is not None,
             **({"rules": rules_out(c["rules"])} if c["rules"] is not None else {})}
            for c in cols
        ],
        "auto_rules": [{"tag": r["tag_name"], "kind": r["kind"], "value": r["value"],
                        "enabled": bool(r["enabled"])} for r in db.get_rules()],
        "files": [
            {"path": f["path"], "name": f["name"], "size": f["size"],
             "tags": sorted(file_tags.get(f["id"], [])), "favorite": bool(f["favorite"]),
             "collections": sorted(file_cols.get(f["id"], [])),
             "rating": f["rating"], "note": f["note"]}
            for f in db.conn.execute("SELECT * FROM files ORDER BY path")
        ],
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    return len(data["files"])


@dataclass
class ImportReport:
    files_matched: int = 0
    files_unmatched: int = 0
    tags_created: int = 0
    collections_created: int = 0

    def text(self):
        s = (f"Импорт: файлов сопоставлено {self.files_matched}, "
             f"новых тегов {self.tags_created}, новых коллекций {self.collections_created}")
        if self.files_unmatched:
            s += f". Не найдено в библиотеке: {self.files_unmatched}"
        return s


def import_json(db, path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if data.get("format") != FORMAT:
        raise ValueError("Это не файл экспорта Виртуального проводника")
    rep = ImportReport()

    before = {t["name"].lower() for t in db.get_tags_with_counts()}
    tag_ids = {}
    for t in data.get("tags", []):
        if t.get("auto"):
            continue  # авто-теги программа ставит сама
        tid = db.ensure_tag(t["name"], t.get("color"), t.get("group", ""))
        tag_ids[t["name"].lower()] = tid
        if t["name"].lower() not in before:
            rep.tags_created += 1
        if t.get("icon"):
            db.set_tag_icon(tid, t["icon"])

    # вложенность восстанавливаем после того, как все теги созданы
    for t in data.get("tags", []):
        if t.get("parent") and not t.get("auto"):
            child, parent = tag_ids.get(t["name"].lower()), db.ensure_tag(t["parent"])
            tag_ids.setdefault(t["parent"].lower(), parent)
            if child and db.get_tag(child)["parent_id"] is None:
                db.set_parent(child, parent)

    def tag_id(name):
        key = name.lower()
        if key not in tag_ids:
            tag_ids[key] = db.ensure_tag(name)
        return tag_ids[key]

    existing = {c["name"].lower(): c["id"] for c in db.get_collections()}
    col_ids = dict(existing)
    for c in data.get("collections", []):
        if c["name"].lower() in col_ids:
            continue
        rules = None
        if c.get("dynamic"):
            rules = dict(c.get("rules", {}))
            for key in ("tags", "exclude_tags"):
                if key in rules:
                    rules[key] = [tag_id(n) for n in rules[key]]
        cid = db.create_collection(c["name"], rules)
        if cid:
            col_ids[c["name"].lower()] = cid
            rep.collections_created += 1

    for r in data.get("auto_rules", []):
        rid = db.add_rule(tag_id(r["tag"]), r["kind"], r["value"])
        if rid and not r.get("enabled", True):
            db.set_rule_enabled(rid, False)

    auto_names = {t["name"].lower() for t in data.get("tags", []) if t.get("auto")}
    by_path = {os.path.normcase(r["path"]): r["id"] for r in db.conn.execute("SELECT id, path FROM files")}
    for f in data.get("files", []):
        fid = by_path.get(os.path.normcase(f["path"]))
        if fid is None:
            rows = db.conn.execute(
                "SELECT id FROM files WHERE name = ? AND size = ?", (f["name"], f.get("size", -1))
            ).fetchall()
            fid = rows[0]["id"] if len(rows) == 1 else None
        if fid is None:
            rep.files_unmatched += 1
            continue
        rep.files_matched += 1
        for name in f.get("tags", []):
            if name.lower() in auto_names:
                continue  # авто-теги программа ставит сама по расширению
            db.conn.execute("INSERT OR IGNORE INTO file_tags (file_id, tag_id) VALUES (?, ?)",
                            (fid, tag_id(name)))
        if f.get("favorite"):
            db.conn.execute("UPDATE files SET favorite = 1 WHERE id = ?", (fid,))
        if f.get("rating"):
            db.conn.execute("UPDATE files SET rating = ? WHERE id = ? AND rating = 0", (f["rating"], fid))
        if f.get("note"):
            db.conn.execute("UPDATE files SET note = ? WHERE id = ? AND note = ''", (f["note"], fid))
        for name in f.get("collections", []):
            cid = col_ids.get(name.lower())
            if cid:
                db.conn.execute(
                    "INSERT OR IGNORE INTO file_collections (file_id, collection_id) VALUES (?, ?)",
                    (fid, cid))
    db.conn.commit()
    return rep
