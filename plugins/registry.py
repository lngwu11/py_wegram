import json
from typing import Optional

import config
from admin.db import connection, lock

_cache = {}


def _seed_from_yaml() -> None:
    ccy = config.cfg.ccy.model_dump()
    ccy_enabled = bool(ccy.pop("enable", False))
    qhb = config.cfg.qhb.model_dump()
    rows = [
        ("ccy", "猜成语", int(ccy_enabled), json.dumps(ccy, ensure_ascii=False)),
        ("qhb", "抢红包", 1, json.dumps(qhb, ensure_ascii=False)),
    ]
    with lock():
        conn = connection()
        conn.executemany(
            "INSERT INTO plugins (id, name, enabled, config_json) VALUES (?, ?, ?, ?)",
            rows,
        )
        conn.commit()


def load() -> None:
    global _cache
    with lock():
        rows = connection().execute("SELECT id, name, enabled, config_json FROM plugins").fetchall()
    if not rows:
        _seed_from_yaml()
        with lock():
            rows = connection().execute("SELECT id, name, enabled, config_json FROM plugins").fetchall()
    _cache = {
        row["id"]: {
            "id": row["id"],
            "name": row["name"],
            "enabled": bool(row["enabled"]),
            "config": json.loads(row["config_json"] or "{}"),
        }
        for row in rows
    }


def list_plugins() -> list:
    if not _cache:
        load()
    return list(_cache.values())


def enabled(plugin_id: str) -> bool:
    if not _cache:
        load()
    item = _cache.get(plugin_id)
    return bool(item and item["enabled"])


def get_config(plugin_id: str) -> dict:
    if not _cache:
        load()
    item = _cache.get(plugin_id) or {}
    return dict(item.get("config") or {})


def update(plugin_id: str, enabled_flag: Optional[bool] = None, plugin_config: Optional[dict] = None) -> Optional[dict]:
    if not _cache:
        load()
    item = _cache.get(plugin_id)
    if not item:
        return None
    if enabled_flag is not None:
        item["enabled"] = bool(enabled_flag)
    if plugin_config is not None:
        item["config"] = plugin_config
    with lock():
        connection().execute(
            "UPDATE plugins SET enabled=?, config_json=? WHERE id=?",
            (int(item["enabled"]), json.dumps(item["config"], ensure_ascii=False), plugin_id),
        )
        connection().commit()
    return item


load()
