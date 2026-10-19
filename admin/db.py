import json
import os
import sqlite3
import threading

import config

_lock = threading.Lock()
_conn = None


def connection() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        os.makedirs(config.DATA_DIR, exist_ok=True)
        _conn = sqlite3.connect(os.path.join(config.DATA_DIR, "wegram.db"), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS contacts (
                wx_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS group_rooms (
                chatroom_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS plugins (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                enabled INTEGER NOT NULL,
                config_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS group_profiles (
                chatroom_id TEXT PRIMARY KEY,
                group_name TEXT NOT NULL DEFAULT '',
                custom_name TEXT NOT NULL DEFAULT ''
            );
            """
        )
        _conn.commit()
    return _conn


def lock() -> threading.Lock:
    return _lock


def load_contacts() -> list:
    with _lock:
        rows = connection().execute("SELECT payload FROM contacts").fetchall()
    return [json.loads(row["payload"]) for row in rows]


def replace_contacts(contacts: list) -> None:
    with _lock:
        conn = connection()
        conn.execute("DELETE FROM contacts")
        conn.executemany(
            "INSERT INTO contacts (wx_id, payload) VALUES (?, ?)",
            [(item.get("wxId") or "", json.dumps(item, ensure_ascii=False)) for item in contacts if item.get("wxId")],
        )
        conn.commit()


def load_groups() -> dict:
    with _lock:
        rows = connection().execute("SELECT chatroom_id, payload FROM group_rooms").fetchall()
    return {row["chatroom_id"]: json.loads(row["payload"]) for row in rows}


def replace_groups(data: dict) -> None:
    with _lock:
        conn = connection()
        conn.execute("DELETE FROM group_rooms")
        conn.executemany(
            "INSERT INTO group_rooms (chatroom_id, payload) VALUES (?, ?)",
            [(key, json.dumps(value, ensure_ascii=False)) for key, value in data.items()],
        )
        conn.commit()


def upsert_groups(data: dict) -> None:
    with _lock:
        conn = connection()
        conn.executemany(
            """
            INSERT INTO group_rooms (chatroom_id, payload) VALUES (?, ?)
            ON CONFLICT(chatroom_id) DO UPDATE SET payload=excluded.payload
            """,
            [(key, json.dumps(value, ensure_ascii=False)) for key, value in data.items()],
        )
        conn.commit()


def load_profiles() -> dict:
    with _lock:
        rows = connection().execute(
            "SELECT chatroom_id, group_name, custom_name FROM group_profiles"
        ).fetchall()
    return {row["chatroom_id"]: {"group_name": row["group_name"], "custom_name": row["custom_name"]} for row in rows}


def remember_group_name(chatroom_id: str, group_name: str) -> None:
    group_name = (group_name or "").strip()
    if not chatroom_id or not group_name or group_name == chatroom_id:
        return
    with _lock:
        connection().execute(
            """
            INSERT INTO group_profiles (chatroom_id, group_name, custom_name)
            VALUES (?, ?, '')
            ON CONFLICT(chatroom_id) DO UPDATE SET group_name=excluded.group_name
            """,
            (chatroom_id, group_name),
        )
        connection().commit()


def set_custom_name(chatroom_id: str, custom_name: str) -> None:
    custom_name = (custom_name or "").strip()
    with _lock:
        connection().execute(
            """
            INSERT INTO group_profiles (chatroom_id, group_name, custom_name)
            VALUES (?, '', ?)
            ON CONFLICT(chatroom_id) DO UPDATE SET custom_name=excluded.custom_name
            """,
            (chatroom_id, custom_name),
        )
        connection().commit()


def import_json_once(path: str, reader, writer, empty) -> None:
    """库为空且 JSON 还在时导入，并改名为 .imported。"""
    if not empty() or not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as file:
        data = json.load(file)
    writer(data)
    os.replace(path, path + ".imported")
